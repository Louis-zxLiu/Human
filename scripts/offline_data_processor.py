import os
import sqlite3
import pandas as pd
from app.core.config import resolve_path

def process_excel_to_sqlite():
    """
    Build the visitor behavior analytics table from the competition Excel.
    This dataset is treated as analytics input only and is not part of the
    scenic fact knowledge base.
    """
    excel_path = resolve_path("data/raw_sql_data/景点景区旅游数据行为分析数据.xlsx")
    db_path = resolve_path("data/processed/tourist_behavior.db")
    
    print(f"[*] 开始读取原始 Excel 数据: {excel_path}")
    if not os.path.exists(excel_path):
        print("[-] 错误: 找不到原始 Excel 文件！")
        return
        
    try:
        # 1. 读取 Excel 数据 (假设数据在第一张表)
        df = pd.read_excel(excel_path)
        
        # 2. 数据清洗 (重命名列名以匹配 SQL Agent 的 Schema)
        # 根据 app/rag/sql_agent.py 中的 Schema:
        # tourist_id, user_nickname, age, gender, attraction_name, attraction_type, 
        # visit_date, stay_duration, ticket_cost, food_cost, shopping_cost, 
        # transport_cost, entertainment_cost, total_cost, group_size, satisfaction
        
        # 这里假设原 Excel 的列名是中文，我们需要做映射
        # 注意：你需要根据实际 Excel 的表头修改这个映射字典！
        column_mapping = {
            "游客ID": "tourist_id",
            "昵称": "user_nickname",
            "年龄": "age",
            "性别": "gender",
            "景点名称": "attraction_name",
            "景点类型": "attraction_type",
            "游览日期": "visit_date",
            "停留时间": "stay_duration",
            "门票花费": "ticket_cost",
            "餐饮花费": "food_cost",
            "购物花费": "shopping_cost",
            "交通花费": "transport_cost",
            "娱乐花费": "entertainment_cost",
            "总花费": "total_cost",
            "团队人数": "group_size",
            "满意度评分": "satisfaction"
        }
        
        # 如果原 Excel 是英文列名，或者包含这些中文列名，则进行重命名
        df.rename(columns=column_mapping, inplace=True)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # 3. 写入 SQLite 数据库
        print(f"[*] 正在将数据写入 SQLite 数据库: {db_path}")
        # 如果表存在则替换 (replace)，不写入 DataFrame 的索引列
        with sqlite3.connect(db_path) as conn:
            df.to_sql("tourist_behavior", conn, if_exists="replace", index=False)
            
        print("[+] 离线数据清洗与转换完成！")
        print(f"    共处理了 {len(df)} 条记录。")
        
    except Exception as e:
        print(f"[-] 处理过程中发生错误: {e}")

if __name__ == "__main__":
    process_excel_to_sqlite()
