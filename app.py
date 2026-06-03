import streamlit as st
import pandas as pd
import os
import random
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from PIL import Image

# 1. 网页基础配置
st.set_page_config(page_title="Gemini 考研全效艾宾浩斯工作台", layout="wide")

st.title("🧠 Gemini 考研独享舱 (日历追踪 + 艾宾浩斯引擎)")
st.markdown("---")

# 2. 🔑 密钥配置区
GEMINI_FREE_API_KEY = st.secrets["GEMINI_API_KEY"]


# 3. 数据库与目录初始化
MEDIA_DIR = "uploaded_media"
DB_ERRORS = "gemini_ebbinghaus_db.xlsx"
if not os.path.exists(MEDIA_DIR): os.makedirs(MEDIA_DIR)

def load_data():
    if os.path.exists(DB_ERRORS):
        try: 
            df = pd.read_excel(DB_ERRORS)
            if "录入日期" not in df.columns:
                df["录入日期"] = datetime.today().date()
            return df
        except: pass
    return pd.DataFrame(columns=["题目ID", "科目", "考点标签", "题目内容", "错误次数", "附件路径", "NextReview", "StageInterval", "录入日期"])

df_errors = load_data()

if not df_errors.empty:
    df_errors["NextReview"] = pd.to_datetime(df_errors["NextReview"]).dt.date
    df_errors["录入日期"] = pd.to_datetime(df_errors["录入日期"]).dt.date

# 4. 核心逻辑：从数据库里动态提取所有科目
if not df_errors.empty and "科目" in df_errors.columns:
    existing_subjects = sorted(list(df_errors["科目"].dropna().unique().tolist()))
else:
    existing_subjects = []

# 5. 页面大布局：左右分栏
col_left, col_right = st.columns([3, 2])

# ==================== 左侧：全动态科目管理与错题流 ====================
with col_left:
    selected_subject = None
    
    if existing_subjects:
        selected_subject = st.segmented_control("🏷️ **当前正在复习的科目：**", options=existing_subjects, default=existing_subjects[0])
    else:
        st.info("💡 你的智能错题本目前还是空的哦！请使用下方组件批量拍图或上传PDF讲义开始吧！")
    
    upload_tab1, upload_tab2 = st.tabs(["📸 单题手拍/PDF快记", "⚡ 多文件闪电批量导入"])
    
    # --- 通道 1：单题拍照/PDF ---
    with upload_tab1:
        uploaded_file = st.file_uploader("上传当前错题图片或 PDF 讲义", type=["png", "jpg", "jpeg", "pdf"], key="single_file")
        
        if "gemini_subject" not in st.session_state: st.session_state.gemini_subject = ""
        if "gemini_content" not in st.session_state: st.session_state.gemini_content = ""
        
        if uploaded_file is not None and st.button("🤖 召唤 Gemini 视觉引擎提取内容", key="btn_single"):
            try:
                with st.spinner("Gemini 正在全神贯注地审阅您的文件..."):
                    client = genai.Client(api_key=GEMINI_FREE_API_KEY)
                    prompt = (
                        "你是一个极其专业的考研错题智能扫描仪。请仔细阅读并看懂我上传的文件里的题目内容。\n"
                        "请严格按照以下格式输出你的分析结果，不要带有任何多余的解释文字：\n"
                        "考点: [请提取1-2个核心薄弱考点标签，用逗号隔开]\n"
                        "题目内容: [请把文件里的题目文本、数字、LaTex格式的数学公式完整抠出来并排版好]"
                    )
                    
                    mime_type = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"
                    doc_part = types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=mime_type)
                    
                    response = client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                    st.session_state.gemini_subject = selected_subject if selected_subject else ""
                    st.session_state.gemini_content = response.text
            except Exception as e:
                st.error(f"Gemini 引擎调用失败: {e}")
                    
        with st.form("add_form", clear_on_submit=True):
            default_sub_name = selected_subject if selected_subject else ""
            sub_m = st.text_input("新建或确认科目 Label", value=st.session_state.gemini_subject if st.session_state.gemini_subject else default_sub_name)
            tag_m = st.text_input("确认考点标签")
            txt_m = st.text_area("题目文本描述", value=st.session_state.gemini_content)
            
            if st.form_submit_button("确认单题入库 💾"):
                if not sub_m.strip():
                    st.error("❌ 科目名称不能为空！")
                else:
                    f_path = ""
                    if uploaded_file is not None:
                        f_path = os.path.join(MEDIA_DIR, uploaded_file.name)
                        with open(f_path, "wb") as f: f.write(uploaded_file.getbuffer())
                    
                    new_row = {
                        "题目ID": f"GEM_{random.randint(100,999)}", "科目": sub_m.strip(),
                        "考点标签": tag_m.strip(), "题目内容": txt_m.strip(), "错误次数": 1, "附件路径": f_path,
                        "NextReview": datetime.today().date(), "StageInterval": 1,
                        "录入日期": datetime.today().date()
                    }
                    df_errors = pd.concat([df_errors, pd.DataFrame([new_row])], ignore_index=True)
                    df_errors.to_excel(DB_ERRORS, index=False)
                    st.session_state.gemini_subject = ""; st.session_state.gemini_content = ""
                    st.success(f"同步成功！")
                    st.rerun()

    # --- 通道 2：图片/PDF 混传批量导入 ---
    with upload_tab2:
        bulk_files = st.file_uploader(
            "选取多份错题文件（支持图片与 PDF 混选）", 
            type=["png", "jpg", "jpeg", "pdf"], 
            accept_multiple_files=True,
            key="bulk_uploader"
        )
        
        if bulk_files:
            bulk_sub_default = st.text_input("为这批文件设定目标【科目Label】", value=selected_subject if selected_subject else "高等数学")
            
            if st.button("🚀 启动 Gemini 流水线批量合流", type="primary"):
                progress_bar = st.progress(0)
                success_count = 0
                client = genai.Client(api_key=GEMINI_FREE_API_KEY)
                
                for idx, file_obj in enumerate(bulk_files):
                    try:
                        f_path = os.path.join(MEDIA_DIR, file_obj.name)
                        with open(f_path, "wb") as f: f.write(file_obj.getbuffer())
                        
                        prompt = (
                            "定位于考研专家视角。请帮我把这个文件里的题目文本、 LaTex格式的公式完整抠出来并排版好。\n"
                            "请严格按照以下格式输出：\n"
                            "考点: [请提取1个核心考点标签]\n"
                            "题目内容: [请把题目文字及公式完整提取出来]"
                        )
                        
                        mime_type = "application/pdf" if file_obj.name.lower().endswith(".pdf") else "image/jpeg"
                        doc_part = types.Part.from_bytes(data=file_obj.getvalue(), mime_type=mime_type)
                        
                        response = client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                        ai_res = response.text
                        
                        parsed_tag = "批量合流"
                        if "考点:" in ai_res:
                            try: parsed_tag = ai_res.split("考点:")[1].split("\n")[0].strip()
                            except: pass
                        
                        new_bulk_row = {
                            "题目ID": f"BLK_{random.randint(1000,9999)}", "科目": bulk_sub_default.strip(),
                            "考点标签": parsed_tag, "题目内容": ai_res, "错误次数": 1, "附件路径": f_path,
                            "NextReview": datetime.today().date(), "StageInterval": 1,
                            "录入日期": datetime.today().date()
                        }
                        
                        df_errors = pd.concat([df_errors, pd.DataFrame([new_bulk_row])], ignore_index=True)
                        success_count += 1
                        
                    except Exception as e:
                        st.error(f"第 {idx+1} 份文件 [{file_obj.name}] 识别失败: {e}")
                    
                    progress_bar.progress((idx + 1) / len(bulk_files))
                
                df_errors.to_excel(DB_ERRORS, index=False)
                st.success(f"🎉 闪电流水线完成！成功处理了 {success_count} 份文件！")
                st.rerun()

    st.markdown("---")
    
    # 复习流控制面板
    if selected_subject:
        sub_df = df_errors[df_errors["科目"] == selected_subject]
        today_date = datetime.today().date()
        today_due_df = sub_df[sub_df["NextReview"] <= today_date] if not sub_df.empty else pd.DataFrame()
        
        view_mode = st.radio("切换复习视角：", [
            f"🔥 艾宾浩斯今日必刷 ({len(today_due_df)}题)", 
            f"📚 全量历史全集 ({len(sub_df)}题)",
            "📅 按日历日期回顾"
        ], horizontal=True)
        
        display_df = pd.DataFrame()
        
        if "今日必刷" in view_mode:
            display_df = today_due_df
        elif "全集" in view_mode:
            display_df = sub_df
        else:
            st.markdown("##### 🗓️ 错题时间轴")
            selected_date = st.date_input("请选择你想查看哪一天录入的错题：", value=datetime.today().date())
            display_df = sub_df[sub_df["录入日期"] == selected_date] if not sub_df.empty else pd.DataFrame()
            st.info(f"在 {selected_date} 这一天，共记录了 {len(display_df)} 道题目。")
        
        current_focus_content = ""
        
        if display_df.empty:
            st.success("这个视图下目前没有题目哦。")
        else:
            q_ids = display_df["题目ID"].tolist()
            selected_q_id = st.selectbox("🎯 选定当前正在攻坚的题目编号：", q_ids)
            q_row = display_df[display_df["题目ID"] == selected_q_id].iloc[0]
            current_focus_content = q_row['题目内容']
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 1.5, 1.5])
                c1.markdown(f"📚 **{q_row['科目']}**")
                c2.markdown(f"🎯 **考点:** {q_row['考点标签']}")
                c3.markdown(f"⏳ **生成日期:** {q_row['录入日期']}")
                st.markdown(f"##### 题目 ID：#{q_row['题目ID']} (历史做错 {q_row['错误次数']} 次)")
                
                txt_show = q_row['题目内容'] if pd.notna(q_row['题目内容']) else '（暂无文字，请看下方原件）'
                st.info(txt_show)
                
                path = q_row["附件路径"]
                if pd.notna(path) and path != "" and os.path.exists(path):
                    if path.lower().endswith(".pdf"):
                        with open(path, "rb") as f:
                            st.download_button("📄 打开/下载完整的 PDF 原件", data=f, file_name=os.path.basename(path), key=f"dl_{q_row['题目ID']}")
                    else:
                        st.image(path, use_container_width=True)
            
            st.markdown("#### 💡 本轮掌握情况")
            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("🔴 遗忘（没思路，明天强制再刷）", use_container_width=True):
                idx = df_errors[df_errors["题目ID"] == selected_q_id].index[0]
                df_errors.at[idx, "StageInterval"] = 1
                df_errors.at[idx, "NextReview"] = datetime.today().date() + timedelta(days=1)
                df_errors.at[idx, "错误次数"] = int(df_errors.at[idx, "错误次数"]) + 1
                df_errors.to_excel(DB_ERRORS, index=False)
                st.rerun()
                
            if btn_col2.button("🟢 顺畅做对（自动延长记忆间隔）", use_container_width=True):
                idx = df_errors[df_errors["题目ID"] == selected_q_id].index[0]
                current_interval = df_errors.at[idx, "StageInterval"]
                if pd.isna(current_interval) or current_interval == 0: current_interval = 1
                next_interval = 3 if current_interval == 1 else (7 if current_interval == 3 else current_interval * 2)
                df_errors.at[idx, "StageInterval"] = next_interval
                df_errors.at[idx, "NextReview"] = datetime.today().date() + timedelta(days=int(next_interval))
                df_errors.to_excel(DB_ERRORS, index=False)
                st.rerun()

# ==================== 右侧：原生高科技 Gemini 备考聊天流 ====================
with col_right:
    st.subheader("🤖 Gemini 考研智能私教舱")
    if selected_subject and 'selected_q_id' in locals() and current_focus_content:
        st.caption(f"🎯 **联动状态：** 已自动锁定左侧【{selected_subject}】题目 `#{selected_q_id}`。")
    else:
        st.caption("🔍 **联动状态：** 自由提问模式。")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [{"role": "assistant", "content": "你好！我是你的考研全科 AI 助教。请随时向我提问，我将用最严密的逻辑为你进行全步骤推导排版！"}]

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.write(msg["content"])

    if user_query := st.chat_input("向 Gemini 提问..."):
        with st.chat_message("user"): st.write(user_query)
        st.session_state.chat_history.append({"role": "user", "content": user_query})

        with st.chat_message("assistant"):
            with st.spinner("Gemini 正在严密审题并组织考研级得分点推导..."):
                try:
                    client = genai.Client(api_key=GEMINI_FREE_API_KEY)
                    context_prompt = f"针对硕士研究生入学考试标准进行深度推导排版。"
                    if selected_subject:
                        context_prompt += f"当前学生正在复习科目：【{selected_subject}】。\n"
                    if 'current_focus_content' in locals() and current_focus_content:
                        context_prompt += f"他卡在了这道错题上：\n\"\"\"{current_focus_content}\"\"\"\n"
                    context_prompt += f"现在学生向你请教：{user_query}\n请给出详细解答，支持使用 LaTeX 公式排版。"
                    
                    response = client.models.generate_content(model='gemini-2.5-flash', contents=context_prompt)
                    st.write(response.text)
                    st.session_state.chat_history.append({"role": "assistant", "content": response.text})
                except Exception as e:
                    st.error(f"对话引擎调用失败: {e}")
