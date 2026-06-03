import streamlit as st
import pandas as pd
import os
import random
import calendar
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from PIL import Image

# 1. 网页基础配置
st.set_page_config(page_title="Gemini 考研全效艾宾浩斯工作台", layout="wide")

st.title("🧠 Gemini 考研独享舱 (日历可视化最终完全体)")
st.markdown("---")

# 2. 🔑 密钥配置区（已完美切回隐藏保险箱，100% 保护你的隐私安全）
GEMINI_FREE_API_KEY = st.secrets["GEMINI_API_KEY"]

# 🛠️ 网络头装甲：强行注入自定义头，彻底破除 SDK 对非 AIzaSy 开头新密钥误判为 Bearer 令牌的底层 Bug
CORE_HTTP_OPTIONS = {
    "headers": {
        "x-goog-api-key": GEMINI_FREE_API_KEY,
        "Authorization": ""  # 极其关键：强行抹除并清空被 SDK 误注入的 Bearer 认证头，解开 401 死锁
    }
}

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
        except Exception as e:
            st.error(f"⚠️ 数据库读取流发生异常: {e}")
    return pd.DataFrame(columns=["题目ID", "科目", "考点标签", "题目内容", "错误次数", "附件路径", "NextReview", "StageInterval", "录入日期"])

df_errors = load_data()

if not df_errors.empty:
    df_errors["NextReview"] = pd.to_datetime(df_errors["NextReview"]).dt.date
    df_errors["录入日期"] = pd.to_datetime(df_errors["录入日期"]).dt.date

# 4. 从数据库里动态提取所有已有科目
if not df_errors.empty and "科目" in df_errors.columns:
    existing_subjects = sorted(list(df_errors["科目"].dropna().unique().tolist()))
else:
    existing_subjects = []

# 初始化平板级暂存沙盒（防止重载掉队）
if "sandbox_tag" not in st.session_state: st.session_state.sandbox_tag = ""
if "sandbox_content" not in st.session_state: st.session_state.sandbox_content = ""
if "last_processed_file" not in st.session_state: st.session_state.last_processed_file = None
if "selected_calendar_day" not in st.session_state: st.session_state.selected_calendar_day = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [{"role": "assistant", "content": "你好！我是你的考研全科 AI 助教。左侧题目扫描成功后，我已实时同步进我的大脑。请随时向我提问，我将用最严密的逻辑为你进行全步骤公式推导排版！"}]

# 💡 辅助函数：绘制真正支持高亮和交互的可视化日历
def render_interactive_calendar(df, subject):
    st.markdown(f"##### 📅 【{subject}】艾宾浩斯复习热力月历")
    today = datetime.today()
    year, month = today.year, today.month
    
    # 提取本月该科目所有有复习任务的日期
    subject_df = df[df["科目"] == subject] if not df.empty else pd.DataFrame()
    task_days = []
    if not subject_df.empty:
        task_days = subject_df["NextReview"].apply(lambda x: x.day if x.month == month and x.year == year else 0).tolist()
        task_days = [d for d in task_days if d != 0]

    cal = calendar.monthcalendar(year, month)
    
    # 绘制星期头
    cols_head = st.columns(7)
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    for i, col in enumerate(cols_head):
        col.markdown(f"<center>**{weekdays[i]}**</center>", unsafe_allowed_html=True)
        
    # 循环绘制日期网格按钮
    for week in cal:
        cols_day = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols_day[i].write("")
            else:
                has_task = day in task_days
                # 如果当天有复习任务，名字后面挂个火苗 🔥
                btn_label = f"{day} 🔥" if has_task else f"{day}"
                
                # 平板点击按钮，直接锁定当天日期数据
                if cols_day[i].button(btn_label, key=f"btn_cal_{day}_{random.randint(1000,9999)}", use_container_width=True):
                    st.session_state.selected_calendar_day = datetime(year, month, day).date()

# 5. 页面大布局：左右分栏
col_left, col_right = st.columns([3, 2])

# ==================== 左侧：全动态科目管理与错题流 ====================
with col_left:
    selected_subject = None
    
    if existing_subjects:
        selected_subject = st.segmented_control("🏷️ **当前正在复习的科目：**", options=existing_subjects, default=existing_subjects[0])
    else:
        st.info("💡 你的智能错题本目前还是空的哦！请在下方上传第一道错题快照开始吧！")
    
    upload_tab1, upload_tab2 = st.tabs(["📸 单题 AI 自由智能录入", "⚡ 多文件闪电批量导入"])
    
    # --- 通道 1：单题自由录入流 ---
    with upload_tab1:
        st.markdown("##### 1️⃣ 第一步：选择传图方式（平板大屏强烈推荐使用相册分屏拖拽或直拍）")
        
        upload_mode = st.radio("选择传图媒介：", ["📸 使用平板摄像头直接对着屏幕/试卷拍照", "📁 从系统相册/本地文件选取"], horizontal=True)
        
        uploaded_file = None
        if upload_mode == "📁 从系统相册/本地文件选取":
            uploaded_file = st.file_uploader("点击上传错题图片（支持相册直接拖拽入内）", type=["png", "jpg", "jpeg", "pdf"], key="tablet_uploader")
        else:
            uploaded_file = st.camera_input("请将平板镜头对准错题或电脑屏幕上的讲义")
        
        if uploaded_file is not None:
            file_name = getattr(uploaded_file, "name", f"camera_{random.randint(100,999)}.jpg")
            
            st.image(uploaded_file, caption="👀 错题原件已成功读入平板内存，就绪！", use_container_width=True)
            
            if st.session_state.last_processed_file != file_name:
                st.session_state.sandbox_tag = ""
                st.session_state.sandbox_content = ""
                st.session_state.last_processed_file = file_name
            
            st.markdown("##### 2️⃣ 第二步：提炼错题详情")
            if st.button("🤖 召唤 Gemini 视觉引擎帮我全自动审题抠字", type="secondary"):
                with st.spinner("🔮 Gemini 正在深度分析快照，自动提炼考点及 LaTeX 公式..."):
                    try:
                        client = genai.Client(api_key=GEMINI_FREE_API_KEY, http_options=CORE_HTTP_OPTIONS)
                        prompt = (
                            "你是一个极其专业的考研错题智能分析专家。请仔细阅读我上传的错题图片。\n"
                            "请严格按照以下格式输出你的分析结果，不要带有任何多余的客套话或解释文本：\n"
                            "考点: [请根据题目内容，精准提炼出1-2个核心薄弱考点标签，如：矩阵的特征值、拉格朗日中值定理、定积分等]\n"
                            "题目内容: [请利用 Markdown 和 LaTeX 语法，把图片里的题目文本、数字、数学公式极其严密完整地抠出来并排版]"
                        )
                        
                        mime_type = "application/pdf" if file_name.lower().endswith(".pdf") else "image/jpeg"
                        doc_part = types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=mime_type)
                        response = client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                        ai_res = response.text
                        
                        if "考点:" in ai_res:
                            try:
                                parts = ai_res.split("考点:")
                                after_tag = parts[1]
                                if "题目内容:" in after_tag:
                                    st.session_state.sandbox_tag = after_tag.split("题目内容:")[0].strip().replace("[", "").replace("]", "")
                                    st.session_state.sandbox_content = after_tag.split("题目内容:")[1].strip()
                                else:
                                    st.session_state.sandbox_tag = after_tag.split("\n")[0].strip().replace("[", "").replace("]", "")
                                    st.session_state.sandbox_content = ai_res
                            except:
                                st.session_state.sandbox_content = ai_res
                        else:
                            st.session_state.sandbox_content = ai_res
                        st.success("🎉 Gemini 扫描提取成功！你可以在下方直接修改它们。")
                    except Exception as e:
                        st.error(f"❌ Gemini 引擎分析失败: {e}")
            
            st.markdown("---")
            base_subjects = ["高等数学", "线性代数", "考研英语", "专业课"]
            combined_subs = sorted(list(set(base_subjects + existing_subjects)))
            
            sub_choice = st.selectbox("🎯 选择已有科目标签（或在下方手写新科目）:", options=["-- ✍️ 自定义手写新科目 --"] + combined_subs)
            
            if sub_choice == "-- ✍️ 自定义手写新科目 --":
                sub_final = st.text_input("📝 请在此手动输入你的新科目名称（例如：高等数学二、英语一）：", value="")
            else:
                sub_final = sub_choice
                
            tag_final = st.text_input("🎯 考点标签确认（支持手写微调）:", value=st.session_state.sandbox_tag)
            content_final = st.text_area("📝 题目文本与公式描述（支持手写微调）:", value=st.session_state.sandbox_content, height=150)
            
            if st.button("💾 确认此错题完美归档入库", type="primary"):
                if not sub_final.strip():
                    st.error("❌ 归档失败：科目名称不能为空，请输入或选择一个科目！")
                else:
                    try:
                        f_path = os.path.join(MEDIA_DIR, file_name)
                        with open(f_path, "wb") as f: f.write(uploaded_file.getvalue())
                        
                        new_row = {
                            "题目ID": f"GEM_{random.randint(100,999)}", "科目": sub_final.strip(),
                            "考点标签": tag_final.strip() if tag_final.strip() else "基础归纳", 
                            "题目内容": content_final.strip() if content_final.strip() else "图片题目", 
                            "错误次数": 1, "附件路径": f_path, "NextReview": datetime.today().date(), "StageInterval": 1,
                            "录入日期": datetime.today().date()
                        }
                        df_errors = pd.concat([df_errors, pd.DataFrame([new_row])], ignore_index=True)
                        df_errors.to_excel(DB_ERRORS, index=False)
                        
                        st.session_state.sandbox_tag = ""
                        st.session_state.sandbox_content = ""
                        st.toast("🎉 错题原图与分析结果已完美合流进艾宾浩斯记忆库！", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 数据写入硬盘失败: {e}")

    # --- 通道 2：批量闪电导入 ---
    with upload_tab2:
        st.markdown("### ⚡ 多文件闪电批量导入")
        with st.form("bulk_data_armored_form"):
            bulk_files = st.file_uploader("选取多份错题文件", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True, key="bulk_uploader")
            bulk_sub_default = st.text_input("为这批文件设定目标【科目Label】", value="线性代数")
            submit_bulk = st.form_submit_button("🚀 启动流水线批量合流", type="primary")
            
        if submit_bulk:
            if not bulk_files:
                st.error("❌ 批量入库失败：你还没有选中任何图片文件！")
            else:
                progress_bar = st.progress(0)
                success_count = 0
                client = genai.Client(api_key=GEMINI_FREE_API_KEY, http_options=CORE_HTTP_OPTIONS)
                
                for idx, file_obj in enumerate(bulk_files):
                    try:
                        f_path = os.path.join(MEDIA_DIR, file_obj.name)
                        with open(f_path, "wb") as f: f.write(file_obj.getvalue())
                        
                        prompt = (
                            "请帮我把这个文件里的题目文本、 LaTex格式的公式完整抠出来并排版好。\n"
                            "请严格按照以下格式输出：\n"
                            "考点: [请提取1个核心考点标签]\n"
                            "题目内容: [请把题目文字及公式完整提取出来]"
                        )
                        mime_type = "application/pdf" if file_obj.name.lower().endswith(".pdf") else "image/jpeg"
                        doc_part = types.Part.from_bytes(data=file_obj.getvalue(), mime_type=mime_type)
                        response = client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                        ai_res = response.text
                        
                        parsed_tag = "批量合流"
                        parsed_content = ai_res
                        if "考点:" in ai_res:
                            try:
                                parts = ai_res.split("考点:")
                                after_tag = parts[1]
                                if "题目内容:" in after_tag:
                                    parsed_tag = after_tag.split("题目内容:")[0].strip().replace("[", "").replace("]", "")
                                    parsed_content = after_tag.split("题目内容:")[1].strip()
                                else:
                                    parsed_tag = after_tag.split("\n")[0].strip().replace("[", "").replace("]", "")
                            except: pass
                        
                        new_bulk_row = {
                            "题目ID": f"BLK_{random.randint(1000,9999)}", "科目": bulk_sub_default.strip(),
                            "考点标签": parsed_tag, "题目内容": parsed_content, 
                            "错误次数": 1, "附件路径": f_path, "NextReview": datetime.today().date(), "StageInterval": 1,
                            "录入日期": datetime.today().date()
                        }
                        df_errors = pd.concat([df_errors, pd.DataFrame([new_bulk_row])], ignore_index=True)
                        success_count += 1
                    except Exception as e:
                        st.error(f"第 {idx+1} 份文件 [{file_obj.name}] 识别失败: {e}")
                    progress_bar.progress((idx + 1) / len(bulk_files))
                
                df_errors.to_excel(DB_ERRORS, index=False)
                st.toast(f"🎉 成功批量处理了 {success_count} 份文件！", icon="🚀")
                st.rerun()

    st.markdown("---")
    
    # 复习流展示面板（无缝集成可视化日历追踪机制）
    if selected_subject:
        sub_df = df_errors[df_errors["科目"] == selected_subject]
        today_date = datetime.today().date()
        today_due_df = sub_df[sub_df["NextReview"] <= today_date] if not sub_df.empty else pd.DataFrame()
        
        # 🌟 三模视角控制台
        view_mode = st.radio("切换复习视角：", [
            f"🔥 艾宾浩斯今日必刷 ({len(today_due_df)}题)", 
            f"📚 全量历史全集 ({len(sub_df)}题)",
            "📅 艾宾浩斯动态日历视图"
        ], horizontal=True)
        
        display_df = pd.DataFrame()
        
        if "今日必刷" in view_mode:
            display_df = today_due_df
        elif "全集" in view_mode:
            display_df = sub_df
        else:
            # 🚀 日历渲染：直接调用高亮追踪日历网格
            with st.container(border=True):
                render_interactive_calendar(df_errors, selected_subject)
                
            if st.session_state.selected_calendar_day:
                st.markdown(f"📌 **当前已选定查看日期：{st.session_state.selected_calendar_day} 的复习日程：**")
                display_df = sub_df[sub_df["NextReview"] == st.session_state.selected_calendar_day] if not sub_df.empty else pd.DataFrame()
            else:
                st.info("💡 请点击上方日历网格中的任意具体日子，即可瞬间下方过滤展示当天的错题攻坚流！")
        
        if display_df.empty:
            if "日历视图" not in view_mode or st.session_state.selected_calendar_day:
                st.success("🎉 太棒了！选定视角下目前没有需要攻坚的题目。")
            st.session_state.current_focus_content = ""
        else:
            q_ids = display_df["题目ID"].tolist()
            selected_q_id = st.selectbox("🎯 选定当前正在攻坚的题目编号：", q_ids)
            q_row = display_df[display_df["题目ID"] == selected_q_id].iloc[0]
            st.session_state.current_focus_content = q_row['题目内容']
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 1.5, 1.5])
                c1.markdown(f"📚 **{q_row['科目']}**")
                c2.markdown(f"🎯 **考点:** {q_row['考点标签']}")
                c3.markdown(f"⏳ **下一次艾宾浩斯复习日:** {q_row['NextReview']}")
                st.markdown(f"##### 题目 ID：#{q_row['题目ID']} (历史做错 {q_row['错误次数']} 次)")
                
                txt_show = q_row['题目内容'] if pd.notna(q_row['题目内容']) else '（暂无文字描述）'
                st.info(txt_show)
                
                # ✨【核心原图平铺原样渲染】百分之百在大框里无缝展示你的网课原图
                path = q_row["附件路径"]
                if pd.notna(path) and path != "" and os.path.exists(path):
                    if path.lower().endswith(".pdf"):
                        with open(path, "rb") as f:
                            st.download_button("📄 打开/下载完整的 PDF 原件", data=f, file_name=os.path.basename(path), key=f"dl_{q_row['题目ID']}")
                    else:
                        st.image(path, caption="📸 错题高清原件原图快照", use_container_width=True)
                else:
                    st.warning("⚠️ 该条历史记录未成功绑定原件图片，请在上方重新正确录入！")
            
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
            
            # 🗑️ 【历史清理模块】一键永久轰炸抹去坏数据/已学会记录
            st.markdown("---")
            if st.button("🗑️ 彻底从错题本中删除此题（清除功能）", use_container_width=True):
                idx = df_errors[df_errors["题目ID"] == selected_q_id].index[0]
                df_errors = df_errors.drop(idx)
                df_errors.to_excel(DB_ERRORS, index=False)
                st.toast("🗑️ 该条记录已被永久扔进回收站！", icon="🗑️")
                st.rerun()

# ==================== 右侧：防平板多发卡死的异步状态机私教舱 ====================
with col_right:
    st.subheader("🤖 Gemini 考研智能私教舱")
    
    focus_content = ""
    if st.session_state.sandbox_content:
        focus_content = st.session_state.sandbox_content
        st.caption("🎯 **联动状态：** 已实时捕获左侧【沙盒暂存区】正在扫描的新错题！")
    elif "current_focus_content" in st.session_state and st.session_state.current_focus_content:
        focus_content = st.session_state.current_focus_content
        st.caption(f"🎯 **联动状态：** 已锁定左侧正在复习的历史题目。")
    else:
        st.caption("🔍 **联动状态：** 自由提问模式。")

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.write(msg["content"])

    if user_query := st.chat_input("向 Gemini 提问..."):
        if st.session_state.chat_history[-1]["content"] != user_query:
            st.session_state.chat_history.append({"role": "user", "content": user_query})
            st.rerun()

    if st.session_state.chat_history[-1]["role"] == "user":
        user_msg = st.session_state.chat_history[-1]["content"]
        with st.chat_message("assistant"):
            with st.spinner("Gemini 正在严密审题并组织考研级得分点推导..."):
                try:
                    client = genai.Client(api_key=GEMINI_FREE_API_KEY, http_options=CORE_HTTP_OPTIONS)
                    context_prompt = f"针对硕士研究生入学考试标准进行深度推导排版。\n"
                    if selected_subject:
                        context_prompt += f"当前学生正在复习科目：【{selected_subject}】。\n"
                    if focus_content:
                        context_prompt += f"他卡在了这道错题上：\n\"\"\"{focus_content}\"\"\"\n"
                    context_prompt += f"现在学生向你请教：{user_msg}\n请给出详细解答，支持使用 LaTeX 公式排版。"
                    
                    response = client.models.generate_content(model='gemini-2.5-flash', contents=context_prompt)
                    st.session_state.chat_history.append({"role": "assistant", "content": response.text})
                    st.rerun()
                except Exception as e:
                    st.error(f"对话引擎调用失败: {e}")
