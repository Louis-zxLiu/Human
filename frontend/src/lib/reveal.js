import { useEffect, useLayoutEffect, useRef } from "react";

const DEFAULT_TARGETS = ".reveal, .reveal-stagger, .reveal-scale, .reveal-left, .reveal-right";
const useBrowserLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function useStableReveal({
  rootSelector,
  targetSelector = DEFAULT_TARGETS,
  visibleClass = "visible",
  childSelector = "",
  childVisibleClass = visibleClass,
  threshold = 0.1,
  rootMargin = "0px 0px -48px 0px",
  staggerMs = 80,
  deps = [],
} = {}) {
  const ref = useRef(null);

  useBrowserLayoutEffect(() => {
    const root = rootSelector ? document.querySelector(rootSelector) : ref.current || document;
    if (!root) return undefined;

    const pendingTimers = new Set();
    const activeTargets = new Set();
    const scheduledTargets = new WeakSet();
    const revealTargets = () => Array.from(root.querySelectorAll(targetSelector));
    const childTargets = (target) => {
      if (!childSelector) return [];
      return Array.from(target.querySelectorAll(childSelector));
    };

    const getDuration = (target) => {
      const classList = target.classList;
      const isHome = target.closest(".home-premium");
      const isScenic = classList.contains("sa-reveal") || classList.contains("sa-reveal-child") || classList.contains("sa-reveal-left") || classList.contains("sa-reveal-right") || classList.contains("sa-reveal-scale");

      if (classList.contains("reveal-left") || classList.contains("sa-reveal-left") || classList.contains("sat-reveal-left") || classList.contains("pln-reveal-left")) {
        return isHome ? 800 : 760;
      }
      if (classList.contains("reveal-right") || classList.contains("sa-reveal-right") || classList.contains("sat-reveal-right") || classList.contains("pln-reveal-right")) {
        return isHome ? 800 : 760;
      }
      if (classList.contains("reveal-scale") || classList.contains("sa-reveal-scale") || classList.contains("sat-reveal-scale") || classList.contains("pln-reveal-scale")) {
        return 720;
      }
      if (classList.contains("pln-reveal-stagger")) {
        return 700;
      }
      if (classList.contains("sa-reveal-child")) {
        return 620;
      }
      if (classList.contains("sat-reveal-child")) {
        return 620;
      }
      if (classList.contains("reveal-child")) {
        return 620;
      }
      if (classList.contains("img-reveal") || classList.contains("char-reveal")) {
        return 420;
      }
      return isScenic ? 900 : 820;
    };

    const getTransitionDelay = (target) => {
      const delay = window.getComputedStyle(target).transitionDelay || "0s";
      return Math.max(
        0,
        ...delay.split(",").map((part) => {
          const value = part.trim();
          if (value.endsWith("ms")) return Number.parseFloat(value) || 0;
          if (value.endsWith("s")) return (Number.parseFloat(value) || 0) * 1000;
          return 0;
        })
      );
    };

    const finishVisible = (target) => {
      target.style.transition = "none";
      target.style.opacity = "1";
      if (!target.matches(".tilt-card, .sa-tilt-card, .sat-tilt-card, .pln-tilt-card")) {
        if (target.matches(".reveal-scale, .sa-reveal-scale, .sat-reveal-scale, .pln-reveal-scale")) {
          target.style.transform = "scale(1)";
        } else if (target.matches(".reveal-left, .reveal-right, .sa-reveal-left, .sa-reveal-right, .sat-reveal-left, .sat-reveal-right, .pln-reveal-left, .pln-reveal-right")) {
          target.style.transform = "translateX(0)";
        } else {
          target.style.transform = "translateY(0)";
        }
      }
      target.style.filter = "none";
      delete target.dataset.revealAnimating;
      delete target.dataset.revealStartedAt;
      target.dataset.revealDone = "true";
      activeTargets.delete(target);
    };

    const animateVisible = (target, addClass) => {
      if (target.dataset.revealDone === "true") {
        target.classList.add(addClass);
        finishVisible(target);
        return;
      }
      if (target.dataset.revealAnimating === "true") {
        target.classList.add(addClass);
        return;
      }

      const duration = getDuration(target);
      target.dataset.revealAnimating = "true";
      target.dataset.revealStartedAt = String(Date.now());
      activeTargets.add(target);
      target.getBoundingClientRect();
      target.classList.add(addClass);
      const transitionDelay = getTransitionDelay(target);

      const onTransitionEnd = (event) => {
        if (event.target === target && target.dataset.revealDone !== "true") {
          finishVisible(target);
        }
      };
      target.addEventListener("transitionend", onTransitionEnd, { once: true });

      const finishTimer = window.setTimeout(() => {
        if (target.dataset.revealDone !== "true") {
          finishVisible(target);
        }
      }, duration + transitionDelay + 220);
      pendingTimers.add(finishTimer);

      const checkTimer = window.setTimeout(() => {
        if (target.dataset.revealDone === "true") return;
        const opacity = Number(window.getComputedStyle(target).opacity);
        if (!Number.isFinite(opacity) || opacity <= 0.01) {
          finishVisible(target);
        }
      }, transitionDelay + 220);
      pendingTimers.add(checkTimer);
    };

    const markVisible = (target, delayChildren = true) => {
      childTargets(target).forEach((child, index) => {
        const apply = () => animateVisible(child, childVisibleClass);
        if (delayChildren && staggerMs > 0) {
          const timer = window.setTimeout(apply, index * staggerMs);
          pendingTimers.add(timer);
        } else {
          apply();
        }
      });
      animateVisible(target, visibleClass);
    };
    const scheduleMarkVisible = (target, delayChildren = true) => {
      if (target.classList.contains(visibleClass)) {
        markVisible(target, false);
        return;
      }
      if (scheduledTargets.has(target)) return;
      scheduledTargets.add(target);

      let secondFrame = 0;
      const firstFrame = window.requestAnimationFrame(() => {
        secondFrame = window.requestAnimationFrame(() => {
          markVisible(target, delayChildren);
        });
      });
    };
    const markVisibleIfInViewport = (target) => {
      const rect = target.getBoundingClientRect();
      const triggerLine = window.innerHeight + Math.min(160, window.innerHeight * 0.18);
      const isBeforeViewportEnd = rect.top < triggerLine;
      const isNearDocumentEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 24;
      if (isBeforeViewportEnd || isNearDocumentEnd) {
        markVisible(target);
        return true;
      }
      return false;
    };

    const prefersReduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let observer;

    if (!("IntersectionObserver" in window) || prefersReduced) {
      revealTargets().forEach((target) => markVisible(target, false));
      return undefined;
    }

    const observe = () => {
      revealTargets().forEach((target) => {
        if (target.classList.contains(visibleClass)) {
          markVisible(target, false);
          return;
        }
        if (!markVisibleIfInViewport(target)) {
          observer.observe(target);
        }
      });
    };

    observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          scheduleMarkVisible(entry.target);
          observer.unobserve(entry.target);
        });
      },
      { threshold, rootMargin }
    );

    observe();
    const retry = window.setTimeout(observe, 250);
    pendingTimers.add(retry);
    const mutationObserver = new MutationObserver(() => {
      window.requestAnimationFrame(observe);
    });
    mutationObserver.observe(root, { childList: true, subtree: true });

    window.addEventListener("scroll", observe, { passive: true });
    window.addEventListener("resize", observe);

    const settleActiveTargets = () => {
      activeTargets.forEach((target) => {
        if (target.dataset.revealDone === "true") return;
        const startedAt = Number(target.dataset.revealStartedAt || 0);
        const elapsed = startedAt ? Date.now() - startedAt : 0;
        const opacity = Number(window.getComputedStyle(target).opacity);
        const delay = getTransitionDelay(target);
        if (elapsed > getDuration(target) + delay + 260 || (elapsed > delay + 220 && (!Number.isFinite(opacity) || opacity <= 0.01))) {
          finishVisible(target);
        }
      });
    };
    const settleTimer = window.setInterval(settleActiveTargets, 220);
    pendingTimers.add(settleTimer);

    return () => {
      activeTargets.forEach((target) => finishVisible(target));
      pendingTimers.forEach((timer) => {
        window.clearTimeout(timer);
        window.clearInterval(timer);
      });
      observer.disconnect();
      mutationObserver.disconnect();
      window.removeEventListener("scroll", observe);
      window.removeEventListener("resize", observe);
    };
  }, deps);

  return ref;
}
