import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image

from app.api.auth import get_current_user
from app.api.memory3d import memory3d_generate
from app.services.memory3d_service import (
    Memory3DPaths,
    Memory3DService,
    Memory3DValidationError,
    reset_memory3d_service_for_tests,
)


def jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 10), color=(40, 120, 180)).save(buffer, format="JPEG")
    return buffer.getvalue()


class Memory3DServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.paths = Memory3DPaths(
            workspace=root,
            inputs=root / "inputs",
            outputs=root / "outputs",
            thumbnails=root / "thumbnails",
        )
        for path in (self.paths.inputs, self.paths.outputs, self.paths.thumbnails):
            path.mkdir(parents=True, exist_ok=True)
        self.model_dir = root / "models" / "apple-sharp"
        self.model_dir.mkdir(parents=True, exist_ok=True)
        (self.model_dir / "sharp_2572gikvuh.pt").write_bytes(b"fake checkpoint")
        self.service = Memory3DService(
            paths=self.paths,
            sharp_command=sys.executable,
            device="cpu",
            allowed_extensions={".jpg", ".jpeg"},
            max_image_mb=1,
            model_dir=self.model_dir,
            start_worker=False,
        )
        reset_memory3d_service_for_tests(self.service)

    def tearDown(self):
        reset_memory3d_service_for_tests(None)
        self.temp_dir.cleanup()

    async def upload(self, filename, content):
        return await memory3d_generate(
            file=[UploadFile(file=io.BytesIO(content), filename=filename)],
            _={"id": 1, "username": "tester", "role": "user"},
        )

    def test_auth_dependency_requires_login(self):
        with self.assertRaises(HTTPException) as context:
            import asyncio

            asyncio.run(get_current_user(None))

        self.assertEqual(context.exception.status_code, 401)

    def test_rejects_unsupported_upload_type(self):
        import asyncio

        with self.assertRaises(HTTPException) as context:
            asyncio.run(self.upload("note.txt", b"hello"))

        self.assertEqual(context.exception.status_code, 400)

    def test_engine_unavailable_returns_503(self):
        unavailable = Memory3DService(
            paths=self.paths,
            sharp_command="definitely-missing-sharp-command",
            start_worker=False,
        )
        reset_memory3d_service_for_tests(unavailable)

        import asyncio

        with self.assertRaises(HTTPException) as context:
            asyncio.run(self.upload("photo.jpg", jpeg_bytes()))

        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("Sharp CLI", context.exception.detail)

    def test_upload_queues_and_cancels_task(self):
        import asyncio

        response = asyncio.run(self.upload("photo.jpg", jpeg_bytes()))
        task_id = response["tasks"][0]["id"]
        self.assertEqual(response["tasks"][0]["name"], "photo")

        _, has_active = self.service.list_tasks()
        self.assertTrue(has_active)

        cancel_response = self.service.cancel_task(task_id)
        self.assertTrue(cancel_response["success"])

    def test_sharp_command_uses_project_checkpoint(self):
        command = self.service.build_sharp_command(self.paths.inputs / "photo.jpg")

        self.assertIn("-c", command)
        checkpoint = command[command.index("-c") + 1]
        self.assertEqual(Path(checkpoint), self.model_dir / "sharp_2572gikvuh.pt")

    def test_delete_model_removes_matching_task_and_files(self):
        task = self.service.enqueue_upload("photo.jpg", jpeg_bytes())
        item_id = task["item_id"]
        (self.paths.outputs / f"{item_id}.ply").write_text(
            "ply\nformat ascii 1.0\nelement vertex 0\nend_header\n",
            encoding="utf-8",
        )
        (self.paths.outputs / f"{item_id}.spz").write_bytes(b"spz")

        self.service.delete_model(item_id)

        tasks, has_active = self.service.list_tasks()
        self.assertFalse(has_active)
        self.assertFalse(any(item["item_id"] == item_id for item in tasks))
        self.assertFalse((self.paths.outputs / f"{item_id}.ply").exists())
        self.assertFalse((self.paths.outputs / f"{item_id}.spz").exists())
        self.assertIsNone(self.service.find_original_image(item_id))

    def test_process_task_completes_with_ply_fallback_when_spz_conversion_missing(self):
        task = self.service.enqueue_upload("photo.jpg", jpeg_bytes())
        item_id = task["item_id"]
        script = textwrap.dedent(
            """
            import pathlib
            import sys

            output_dir = pathlib.Path(sys.argv[1])
            item_id = pathlib.Path(sys.argv[2]).stem
            (output_dir / f"{item_id}.ply").write_text(
                "ply\\nformat ascii 1.0\\nelement vertex 0\\nend_header\\n",
                encoding="utf-8",
            )
            """
        )
        self.service.build_sharp_command = lambda input_path: [sys.executable, "-c", script, str(self.paths.outputs), str(input_path)]
        self.service.try_convert_spz = lambda ply_path: None

        self.service.process_task(task["id"])

        tasks, _ = self.service.list_tasks()
        processed = next(item for item in tasks if item["id"] == task["id"])
        self.assertEqual(processed["status"], "completed")
        gallery = self.service.gallery()
        self.assertEqual(gallery[0]["id"], item_id)
        self.assertEqual(gallery[0]["name"], "photo")
        self.assertIsNone(gallery[0]["spz_url"])

    def test_model_name_can_be_updated_and_deleted_with_metadata(self):
        task = self.service.enqueue_upload("front gate.jpg", jpeg_bytes())
        item_id = task["item_id"]
        (self.paths.outputs / f"{item_id}.ply").write_text(
            "ply\nformat ascii 1.0\nelement vertex 0\nend_header\n",
            encoding="utf-8",
        )

        gallery = self.service.gallery()
        self.assertEqual(gallery[0]["name"], "front gate")

        updated = self.service.set_model_name(item_id, "入口记忆")
        self.assertEqual(updated["name"], "入口记忆")
        self.assertEqual(self.service.gallery()[0]["name"], "入口记忆")

        self.service.delete_model(item_id)
        metadata = json.loads(self.service.metadata_path.read_text(encoding="utf-8"))
        self.assertNotIn(item_id, metadata)

    def test_rejects_path_traversal_for_model_files(self):
        with self.assertRaises(Memory3DValidationError):
            self.service.resolve_output_file("../secret.ply")


if __name__ == "__main__":
    unittest.main()
