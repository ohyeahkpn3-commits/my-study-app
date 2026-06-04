import streamlit as st
import pandas as pd
import os
import random
from datetime import datetime, timedelta
from google import genai
from google.genai import types

# ==========================================
# 1. 网页基础配置与本地安全环境设定
# ==========================================
st.set_page_config(page_title="TabMistake - 考研全效工作台", layout="wide")
st.title("🧠 TabMistake 考研独享舱 (本地免密满血版)")
st.markdown("---")

# 🔑 从本地的 Secrets (.streamlit/secrets.toml) 中安全读取大模型密钥
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# 初始化 Gemini 客户端
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    st.warning("🔑 未在后台检测到 Gemini API Key。你可以在本地项目根目录下创建 `.streamlit/secrets.toml` 并写入 `GEMINI_API_KEY=\"你的密钥\"`")
    user_key_input = st.text_input("或者在这里直接临时贴入你的有效 API 密钥：", type="password")
    if user_key_input:
        ai_client = genai.Client(api_key=user_key_input)
    else:
        ai_client = None

# ==========================================
# 2. 本地虚拟数据库重构 (Pandas CSV 引擎)
# ==========================================
DB_FILE = "study_data_bank.csv"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            df["NextReview"] = pd.to_datetime(df["NextReview"]).dt.date
            df["录入日期"] = pd.to_datetime(df["录入日期"]).dt.date
            return df
        except Exception as e:
            st.error(f"⚠️ 本地数据库加载异常: {e}")
            
    return pd.DataFrame(columns=[
        "题目ID", "科目", "章节", "考点标签", "题目内容", 
        "错误次数", "附件路径", "NextReview", "StageInterval", "录入日期", "来源"
    ])

df_errors = load_data()

base_subjects = ["考研数学二", "考研英语", "控制工程/汽车原理", "专业课"]
existing_subjects = sorted(list(set(base_subjects + (df_errors["科目"].dropna().tolist() if not df_errors.empty else []))))

# ==========================================
# 3. 平板级沙盒状态机初始化
# ==========================================
if "sandbox_chapter" not in st.session_state: st.session_state.sandbox_chapter = ""
if "sandbox_tag" not in st.session_state: st.session_state.sandbox_tag = ""
if "sandbox_content" not in st.session_state: st.session_state.sandbox_content = ""
if "last_processed_file" not in st.session_state: st.session_state.last_processed_file = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [{"role": "assistant", "content": "你好！我是你的专属考研 AI 助教。请随时向我提问，我将用最严谨的逻辑为你进行公式推导排版！"}]
if "current_focus_content" not in st.session_state: st.session_state.current_focus_content = ""
if "current_focus_tag" not in st.session_state: st.session_state.current_focus_tag = ""

# ==========================================
# 4. 页面大布局：左右分栏
# ==========================================
col_left, col_right = st.columns([1.2, 1])

with col_left:
    selected_subject = st.segmented_control("🏷️ **当前攻坚科目：**", options=existing_subjects, default=existing_subjects[0])
    
    upload_tab1, upload_tab2, review_tab3, daily_quiz_tab4 = st.tabs([
        "📸 错题精准录入", "📥 专属题库导入", "📚 历史错题本", "🎯 每日混合抽题"
    ])
    
    with upload_tab1:
        st.markdown("##### 1️⃣ 截屏/拍照直传 (自动标记为【错题】)")
        uploaded_file = st.file_uploader("点击或拖拽错题图片/PDF", type=["png", "jpg", "jpeg", "pdf"], key="single_uploader")
        
        if uploaded_file is not None:
            file_name = getattr(uploaded_file, "name", f"doc_{random.randint(1000,9999)}.pdf")
            file_ext = file_name.lower().split('.')[-1]
            
            if file_ext == "pdf":
                st.success(f"📄 PDF 错题文档 [{file_name}] 已成功读入平板本地内存！")
                mime_type = "application/pdf"
            else:
                st.image(uploaded_file, caption="👀 错题原件已读入本地内存，就绪！", use_container_width=True)
                mime_type = f"image/{file_ext}" if file_ext in ['png', 'jpg', 'jpeg'] else 'image/jpeg'
            
            if st.session_state.last_processed_file != file_name:
                st.session_state.sandbox_chapter = ""
                st.session_state.sandbox_tag = ""
                st.session_state.sandbox_content = ""
                st.session_state.last_processed_file = file_name
            
            if st.button("🤖 召唤 Gemini 提取错题考点", type="secondary"):
                if not ai_client:
                    st.error("请先配置有效的 Gemini API Key！")
                else:
                    with st.spinner("🔮 正在深度解析文档中的数学公式与知识树..."):
                        try:
                            prompt = (
                                "你是一个极其专业的考研辅导专家。请阅读文件中的题目内容。\n"
                                "严格按以下 JSON 格式输出，不要包含 ```json 等标记符：\n"
                                "{\n"
                                '  "章节": "提取所属的大章节，如：多元函数微分学",\n'
                                '  "考点": "提取核心考点，如：全微分求导",\n'
                                '  "内容": "完整提取题目文本，所有数学公式必须使用标准 LaTeX"\n'
                                "}"
                            )
                            doc_part = types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=mime_type)
                            res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                            
                            import json, re
                            json_str = re.search(r'\{.*\}', res.text.replace('\n', ''), re.DOTALL)
                            if json_str:
                                data = json.loads(json_str.group())
                                st.session_state.sandbox_chapter = data.get("章节", "")
                                st.session_state.sandbox_tag = data.get("考点", "")
                                st.session_state.sandbox_content = data.get("内容", "")
                                st.success("🎉 考点和公式抠字成功！你可以在下方直接修改。")
                            else:
                                st.session_state.sandbox_content = res.text
                        except Exception as e:
                            st.error(f"❌ 识别失败: {e}")
            
            st.markdown("---")
            st.markdown("##### 2️⃣ 确认归档标签 (Label)")
            sub_choice = st.selectbox("🎯 确认科目:", options=existing_subjects, index=existing_subjects.index(selected_subject) if selected_subject in existing_subjects else 0)
            
            c1, c2 = st.columns(2)
            chapter_final = c1.text_input("📚 章节归属:", value=st.session_state.sandbox_chapter)
            tag_final = c2.text_input("🎯 核心考点:", value=st.session_state.sandbox_tag)
            content_final = st.text_area("📝 题目公式文本描述:", value=st.session_state.sandbox_content, height=150)
            
            if st.button("💾 作为【错题】保存到本地数据库", type="primary"):
                if not tag_final.strip() or not content_final.strip():
                    st.error("❌ 归档失败：考点标签和题目内容不能为空！")
                else:
                    try:
                        new_row = {
                            "题目ID": f"GEM_{random.randint(10000,99999)}", 
                            "科目": sub_choice,
                            "章节": chapter_final.strip(),
                            "考点标签": tag_final.strip(), 
                            "题目内容": content_final.strip(), 
                            "错误次数": 1, 
                            "附件路径": f"local_memory/{file_name}", 
                            "NextReview": datetime.today().date(), 
                            "StageInterval": 1,
                            "录入日期": datetime.today().date(),
                            "来源": "错题"
                        }
                        df_errors = pd.concat([df_errors, pd.DataFrame([new_row])], ignore_index=True)
                        df_errors.to_csv(DB_FILE, index=False)
                        st.toast("🎉 错题已安全保存至本地！", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 本地写入失败: {e}")

    with upload_tab2:
        st.markdown("### 📥 海量题库单章节批量导入")
        with st.form("bulk_data_form"):
            bulk_files = st.file_uploader("选取按章节拆分好的 PDF", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True, key="bulk_uploader")
            bulk_sub_default = st.selectbox("目标【科目】", options=existing_subjects, index=0)
            parse_limit = st.slider("⚖️ 单次请求提取题目上限", min_value=1, max_value=25, value=5)
            submit_bulk = st.form_submit_button("🚀 作为【题库】批量导入本地", type="primary")
            
        if submit_bulk:
            if not bulk_files or not ai_client:
                st.error("❌ 导入失败：请检查文件或 API Key！")
            else:
                progress_bar = st.progress(0)
                success_count = 0
                for idx, file_obj in enumerate(bulk_files):
                    try:
                        file_ext = file_obj.name.lower().split('.')[-1]
                        mime_type = "application/pdf" if file_ext == "pdf" else (f"image/{file_ext}" if file_ext in ['png', 'jpg', 'jpeg'] else 'image/jpeg')
                        prompt = (
                            f"请从该文件中提炼出最多 {parse_limit} 道题目。\n"
                            "严格按以下 JSON 数组格式输出：\n"
                            "[\n  {\"考点\": \"考点标签\", \"内容\": \"题目完整文本\"}\n]"
                        )
                        doc_part = types.Part.from_bytes(data=file_obj.getvalue(), mime_type=mime_type)
                        res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                        
                        import json, re
                        json_str = re.search(r'\[.*\]', res.text.replace('\n', ''), re.DOTALL)
                        parsed_items = json.loads(json_str.group()) if json_str else [{"考点": "题库流转", "内容": res.text}]
                            
                        for item in parsed_items:
                            new_bulk_row = {
                                "题目ID": f"BANK_{random.randint(100000,999999)}", "科目": bulk_sub_default,
                                "章节": "题库长文档导入", "考点标签": item.get("考点", "未分类"), 
                                "题目内容": item.get("内容", "提取失败"), "错误次数": 0, "附件路径": file_obj.name, 
                                "NextReview": datetime(2099, 12, 31).date(), "StageInterval": 0,
                                "录入日期": datetime.today().date(), "来源": "题库"
                            }
                            df_errors = pd.concat([df_errors, pd.DataFrame([new_bulk_row])], ignore_index=True)
                        success_count += len(parsed_items)
                    except Exception:
                        pass
                    progress_bar.progress((idx + 1) / len(bulk_files))
                
                df_errors.to_csv(DB_FILE, index=False)
                st.toast(f"🚀 成功导入 {success_count} 道题目！", icon="📥")
                st.rerun()

    with review_tab3:
        if not df_errors.empty and selected_subject:
            sub_df = df_errors[(df_errors["科目"] == selected_subject) & (df_errors["来源"] == "错题")]
            today_date = datetime.today().date()
            today_due_df = sub_df[sub_df["NextReview"] <= today_date]
            
            view_mode = st.radio("错题本过滤器：", [f"🔥 今日必刷到期错题 ({len(today_due_df)})", f"📚 历史错题全集 ({len(sub_df)})"], horizontal=True)
            display_df = today_due_df if "今日必刷" in view_mode else sub_df
            
            if not display_df.empty:
                q_ids = display_df["题目ID"].tolist()
                selected_q_id = st.selectbox("🎯 选择当前攻坚错题：", q_ids)
                q_row = display_df[display_df["题目ID"] == selected_q_id].iloc[0]
                
                st.session_state.current_focus_content = q_row['题目内容']
                st.session_state.current_focus_tag = q_row['考点标签']
                
                with st.container(border=True):
                    st.markdown(f"**【{q_row['章节']}】** 考点: `{q_row['考点标签']}` | 错 `{q_row['错误次数']}` 次")
                    st.info(q_row['题目内容'])
                    
                col_btn1, col_btn2 = st.columns(2)
                if col_btn1.button("🔴 遗忘 (明天重刷)", use_container_width=True):
                    idx = df_errors[df_errors["题目ID"] == selected_q_id].index[0]
                    df_errors.at[idx, "StageInterval"] = 1
                    df_errors.at[idx, "NextReview"] = today_date + timedelta(days=1)
                    df_errors.at[idx, "错误次数"] = int(q_row["错误次数"]) + 1
                    df_errors.to_csv(DB_FILE, index=False)
                    st.rerun()
                    
                if col_btn2.button("🟢 做对 (延长周期)", use_container_width=True):
                    idx = df_errors[df_errors["题目ID"] == selected_q_id].index[0]
                    cur_int = int(q_row["StageInterval"]) if pd.notna(q_row["StageInterval"]) else 1
                    next_int = 3 if cur_int == 1 else (7 if cur_int == 3 else cur_int * 2)
                    df_errors.at[idx, "StageInterval"] = next_int
                    df_errors.at[idx, "NextReview"] = today_date + timedelta(days=next_int)
                    df_errors.to_csv(DB_FILE, index=False)
                    st.rerun()
            else:
                st.success("🎉 目前没有到期错题！")

    with daily_quiz_tab4:
        if st.button("🚀 随机组卷 10 道题", type="primary"):
            if not df_errors.empty:
                pool = df_errors[df_errors["科目"] == selected_subject]
                if not pool.empty:
                    due_pool = pool[(pool["来源"] == "错题") & (pool["NextReview"] <= datetime.today().date())]
                    due_samples = due_pool.drop_duplicates(subset=['考点标签']).sample(min(5, len(due_pool)))
                    bank_pool = pool[(pool["来源"] == "题库") & (pool["错误次数"] == 0) & (~pool["题目ID"].isin(due_samples["题目ID"]))]
                    bank_samples = bank_pool.drop_duplicates(subset=['考点标签']).sample(min(10 - len(due_samples), len(bank_pool)))
                    
                    if not due_samples.empty or not bank_samples.empty:
                        quiz_df = pd.concat([due_samples, bank_samples]).sample(frac=1).reset_index(drop=True)
                        st.session_state.current_quiz_list = quiz_df.to_dict('records')
                        
        if "current_quiz_list" in st.session_state and st.session_state.current_quiz_list:
            for idx, item_dict in enumerate(st.session_state.current_quiz_list):
                badge = "🔥 错题回顾" if item_dict['来源'] == '错题' else "✨ 题库新题"
                with st.expander(f"第 {idx+1} 题 | {item_dict['考点标签']} ({badge})"):
                    st.write(item_dict['题目内容'])
                    if item_dict['来源'] == '题库':
                        if st.button("😭 打入错题本", key=f"quiz_{item_dict['题目ID']}"):
                            idx_in_main = df_errors[df_errors["题目ID"] == item_dict['题目ID']].index[0]
                            df_errors.at[idx_in_main, "来源"] = "错题"
                            df_errors.at[idx_in_main, "错误次数"] = 1
                            df_errors.at[idx_in_main, "StageInterval"] = 1
                            df_errors.at[idx_in_main, "NextReview"] = datetime.today().date() + timedelta(days=1)
                            df_errors.to_csv(DB_FILE, index=False)
                            del st.session_state.current_quiz_list
                            st.rerun()

with col_right:
    st.subheader("🤖 核心推导私教舱")
    
    linkage_info = ""
    if st.session_state.current_focus_tag and not df_errors.empty:
        related_df = df_errors[(df_errors["考点标签"] == st.session_state.current_focus_tag) & (df_errors["题目ID"] != st.session_state.get('selected_q_id', ''))]
        if not related_df.empty:
            st.success(f"💡 检测到在本地库中存在 {len(related_df)} 道同类题！")
            linkage_info = f"系统在库中扫描到了关联题目。片段：{related_df.iloc[0]['题目内容'][:60]}..."

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if user_query := st.chat_input("请求推导或纠错..."):
        if st.session_state.chat_history[-1]["content"] != user_query:
            st.session_state.chat_history.append({"role": "user", "content": user_query})
            st.rerun()

    if st.session_state.chat_history[-1]["role"] == "user":
        user_msg = st.session_state.chat_history[-1]["content"]
        with st.chat_message("assistant"):
            if not ai_client:
                st.error("请配置 API 密钥。")
            else:
                with st.spinner("系统正在建立演练..."):
                    context = "你是一位标准阅卷组专家级导师，请使用规范学术语言解答，公式必须使用标准 LaTeX 排版。\n"
                    if selected_subject: context += f"【当前复习科目】：{selected_subject}\n"
                    if st.session_state.current_focus_content: context += f"【当前卡住的题目】：{st.session_state.current_focus_content}\n"
                    if linkage_info: context += f"【同考点历史】：{linkage_info}\n请给出一针见血的点拨。\n"
                    context += f"学生问：{user_msg}\n阅卷导师解答："
                    
                    try:
                        res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=context)
                        st.session_state.chat_history.append({"role": "assistant", "content": res.text})
                        st.rerun()
                    except Exception as e:
                        st.error(f"网络卡顿: {e}")
