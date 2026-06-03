import streamlit as st
import pandas as pd
import os
import random
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from supabase import create_client, Client

# ==========================================
# 1. 网页基础配置与云端安全环境设定
# ==========================================
st.set_page_config(page_title="TabMistake - 考研全效工作台", layout="wide")
st.title("🧠 TabMistake 考研独享舱 (云端全能版)")
st.markdown("---")

# 🔑 从 Streamlit Cloud 的 Secrets 中安全读取密钥
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    st.error("⚠️ 未检测到 Gemini API Key，请在云端 Secrets 中配置！")

# ==========================================
# 2. 云端数据库连接 (Supabase)
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None

supabase = init_supabase()

def load_data():
    """从云端 Supabase 读取全量数据，融合错题与题库"""
    if supabase:
        try:
            response = supabase.table("errors_table").select("*").execute()
            if response.data:
                df = pd.DataFrame(response.data)
                df["NextReview"] = pd.to_datetime(df["NextReview"]).dt.date
                df["录入日期"] = pd.to_datetime(df["录入日期"]).dt.date
                # 兼容旧数据，如果没有"来源"列，默认全部标记为错题
                if "来源" not in df.columns:
                    df["来源"] = "错题"
                return df
        except Exception as e:
            st.error(f"⚠️ 云端数据库读取异常: {e}")
            
    # 保底空表结构，新增【来源】字段
    return pd.DataFrame(columns=["题目ID", "科目", "章节", "考点标签", "题目内容", "错误次数", "附件路径", "NextReview", "StageInterval", "录入日期", "来源"])

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
    st.session_state.chat_history = [{"role": "assistant", "content": "你好！我是你的专属考研 AI 助教。请随时向我提问，我将用最严谨的逻辑为你进行推导！"}]
if "current_focus_content" not in st.session_state: st.session_state.current_focus_content = ""
if "current_focus_tag" not in st.session_state: st.session_state.current_focus_tag = ""

# ==========================================
# 4. 页面大布局：左右分栏
# ==========================================
col_left, col_right = st.columns([1.2, 1])

# ------------------------------------------
# 左侧：全动态科目管理、抽题与题库流
# ------------------------------------------
with col_left:
    selected_subject = st.segmented_control("🏷️ **当前攻坚科目：**", options=existing_subjects, default=existing_subjects[0])
    
    upload_tab1, upload_tab2, review_tab3, daily_quiz_tab4 = st.tabs(["📸 错题精准录入", "📥 专属题库导入", "📚 历史错题本", "🎯 每日混合抽题"])
    
    # --- 通道 1：单题 AI 智能归档 (错题端) ---
    with upload_tab1:
        st.markdown("##### 1️⃣ 截屏/拍照直传 (标记为错题)")
        uploaded_file = st.file_uploader("点击或拖拽错题图片（支持平板直接操作）", type=["png", "jpg", "jpeg", "pdf"], key="single_uploader")
        
        if uploaded_file is not None:
            file_name = getattr(uploaded_file, "name", f"doc_{random.randint(1000,9999)}.pdf")
            file_ext = file_name.lower().split('.')[-1]
            
            if file_ext == "pdf":
                st.success(f"📄 PDF 错题文档 [{file_name}] 已成功读入内存！")
                mime_type = "application/pdf"
            else:
                st.image(uploaded_file, caption="👀 图像已读入内存，就绪！", use_container_width=True)
                mime_type = f"image/{file_ext}" if file_ext in ['png', 'jpg', 'jpeg'] else 'image/jpeg'
            
            if st.session_state.last_processed_file != file_name:
                st.session_state.sandbox_chapter = ""
                st.session_state.sandbox_tag = ""
                st.session_state.sandbox_content = ""
                st.session_state.last_processed_file = file_name
            
            if st.button("🤖 召唤 Gemini 提取错题考点", type="secondary"):
                with st.spinner("🔮 正在深度解析文档中的数学公式与知识树..."):
                    try:
                        prompt = (
                            "你是一个极其专业的考研辅导专家。请阅读文件中的题目内容。\n"
                            "严格按以下 JSON 格式输出，不要包含 ```json 等标记符：\n"
                            "{\n"
                            '  "章节": "提取所属的大章节，如：一元函数积分学",\n'
                            '  "考点": "提取核心考点，如：换元积分法",\n'
                            '  "内容": "完整提取题目文本，所有数学公式必须使用标准 LaTeX (行内用 $, 行间用 $$)"\n'
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
                            st.success("🎉 提取成功！请在下方核对。")
                        else:
                            st.session_state.sandbox_content = res.text
                    except Exception as e:
                        st.error(f"❌ 识别失败: {e}")
            
            st.markdown("---")
            st.markdown("##### 2️⃣ 确认归档标签")
            sub_choice = st.selectbox("🎯 确认科目:", options=existing_subjects, index=existing_subjects.index(selected_subject) if selected_subject in existing_subjects else 0)
            
            c1, c2 = st.columns(2)
            chapter_final = c1.text_input("📚 章节归属:", value=st.session_state.sandbox_chapter)
            tag_final = c2.text_input("🎯 核心考点:", value=st.session_state.sandbox_tag)
            content_final = st.text_area("📝 题目公式文本:", value=st.session_state.sandbox_content, height=150)
            
            if st.button("💾 作为【错题】归档至云端", type="primary"):
                if not tag_final.strip():
                    st.error("❌ 考点标签不能为空！")
                else:
                    try:
                        dummy_img_url = f"cloud_storage_placeholder/{file_name}" 
                        new_row = {
                            "题目ID": f"GEM_{random.randint(10000,99999)}", 
                            "科目": sub_choice,
                            "章节": chapter_final.strip(),
                            "考点标签": tag_final.strip(), 
                            "题目内容": content_final.strip(), 
                            "错误次数": 1, 
                            "附件路径": dummy_img_url, 
                            "NextReview": str(datetime.today().date()), 
                            "StageInterval": 1,
                            "录入日期": str(datetime.today().date()),
                            "来源": "错题"  # 核心改动：打上错题烙印
                        }
                        if supabase:
                            supabase.table("errors_table").insert(new_row).execute()
                            st.toast("🎉 错题已安全入库，开启记忆循环！", icon="✅")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ 数据库写入失败: {e}")

    # --- 通道 2：大容量专属题库导入流 ---
    with upload_tab2:
        st.markdown("### 📥 海量题库/试卷 PDF 导入")
        st.info("💡 **防截断策略**：由于 200MB 的题库过于庞大，大模型单次无法吐出所有题目。请设定每次解析的【题目数量】，系统将进行智能切割。")
        
        with st.form("bulk_data_form"):
            bulk_files = st.file_uploader("选取题库PDF或多份试卷截图", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True, key="bulk_uploader")
            bulk_sub_default = st.selectbox("为这批题库设定目标【科目】", options=existing_subjects, index=0)
            
            parse_limit = st.slider("⚖️ 单次请求提取的题目上限 (防止大模型 JSON 断流崩溃)", min_value=1, max_value=20, value=5)
            submit_bulk = st.form_submit_button("🚀 作为【题库】批量入云", type="primary")
            
        if submit_bulk:
            if not bulk_files:
                st.error("❌ 导入失败：你还没有选中任何文件！")
            else:
                progress_bar = st.progress(0)
                success_count = 0
                
                for idx, file_obj in enumerate(bulk_files):
                    try:
                        file_ext = file_obj.name.lower().split('.')[-1]
                        mime_type = "application/pdf" if file_ext == "pdf" else (f"image/{file_ext}" if file_ext in ['png', 'jpg', 'jpeg'] else 'image/jpeg')
                        
                        prompt = (
                            f"你是一个题库解析引擎。请从该文件中提取最多 {parse_limit} 道题目。\n"
                            "为了建立题库联动，必须严格按以下 JSON 数组格式输出：\n"
                            "[\n"
                            '  {"考点": "提炼1个核心考点", "内容": "题目完整文本及LaTeX公式"},\n'
                            '  {"考点": "提炼另1个核心考点", "内容": "下一道题的文本"}\n'
                            "]"
                        )
                        doc_part = types.Part.from_bytes(data=file_obj.getvalue(), mime_type=mime_type)
                        res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=[doc_part, prompt])
                        
                        import json, re
                        # 尝试捕获返回的 JSON 数组
                        json_str = re.search(r'\[.*\]', res.text.replace('\n', ''), re.DOTALL)
                        parsed_items = []
                        
                        if json_str:
                            try:
                                parsed_items = json.loads(json_str.group())
                            except:
                                parsed_items = [{"考点": "题库批量解析异常", "内容": res.text}]
                        else:
                            parsed_items = [{"考点": "题库批量提取", "内容": res.text}]
                            
                        # 循环将多道题写入数据库
                        for item in parsed_items:
                            tag = item.get("考点", "未分类题库")
                            content = item.get("内容", "内容提取失败")
                            
                            dummy_img_url = f"cloud_storage_placeholder/{file_obj.name}" 
                            new_bulk_row = {
                                "题目ID": f"BANK_{random.randint(100000,999999)}", 
                                "科目": bulk_sub_default,
                                "章节": "题库导入",
                                "考点标签": tag, 
                                "题目内容": content, 
                                "错误次数": 0,  # 题库新题，错误次数默认为0
                                "附件路径": dummy_img_url, 
                                "NextReview": "2099-12-31", # 题库新题不进入强制艾宾浩斯，直到它被抽中并做错
                                "StageInterval": 0,
                                "录入日期": str(datetime.today().date()),
                                "来源": "题库" # 核心改动：打上题库烙印
                            }
                            
                            if supabase:
                                supabase.table("errors_table").insert(new_bulk_row).execute()
                                success_count += 1
                            
                    except Exception as e:
                        st.error(f"文件 [{file_obj.name}] 解析或入库失败: {e}")
                    
                    progress_bar.progress((idx + 1) / len(bulk_files))
                
                st.toast(f"🎉 成功从题库文件中解析并录入了 {success_count} 道新题！", icon="🚀")
                st.rerun()

    # --- 通道 3：复习流展示面板 (错题本专区) ---
    with review_tab3:
        if not df_errors.empty and selected_subject:
            # 这里的复习面板只看【错题】
            sub_df = df_errors[(df_errors["科目"] == selected_subject) & (df_errors["来源"] == "错题")]
            today_date = datetime.today().date()
            today_due_df = sub_df[sub_df["NextReview"] <= today_date]
            
            view_mode = st.radio("错题本视角：", [f"🔥 今日必刷错题 ({len(today_due_df)})", f"📚 历史错题全集 ({len(sub_df)})"], horizontal=True)
            display_df = today_due_df if "今日必刷" in view_mode else sub_df
            
            if not display_df.empty:
                q_ids = display_df["题目ID"].tolist()
                selected_q_id = st.selectbox("🎯 选择攻坚题目：", q_ids)
                q_row = display_df[display_df["题目ID"] == selected_q_id].iloc[0]
                
                st.session_state.current_focus_content = q_row['题目内容']
                st.session_state.current_focus_tag = q_row['考点标签']
                
                with st.container(border=True):
                    st.markdown(f"**【{q_row['章节']}】** 考点: `{q_row['考点标签']}` | 历史错误: {q_row['错误次数']}次")
                    st.info(q_row['题目内容'])
                    
                col_btn1, col_btn2 = st.columns(2)
                if col_btn1.button("🔴 再次遗忘 (明天重刷)", key="btn_forget", use_container_width=True):
                    if supabase:
                        supabase.table("errors_table").update({"StageInterval": 1, "NextReview": str(today_date + timedelta(days=1)), "错误次数": int(q_row["错误次数"]) + 1}).eq("题目ID", selected_q_id).execute()
                        st.rerun()
                if col_btn2.button("🟢 顺畅掌握 (延长记忆间隔)", key="btn_pass", use_container_width=True):
                    if supabase:
                        current_interval = int(q_row["StageInterval"]) if pd.notna(q_row["StageInterval"]) else 1
                        next_interval = 3 if current_interval == 1 else (7 if current_interval == 3 else current_interval * 2)
                        supabase.table("errors_table").update({"StageInterval": next_interval, "NextReview": str(today_date + timedelta(days=next_interval))}).eq("题目ID", selected_q_id).execute()
                        st.rerun()
            else:
                st.success("🎉 这个视角下没有需要复习的错题！")

    # --- 通道 4：抗遗忘每日混合抽题 ---
    with daily_quiz_tab4:
        st.markdown("##### 🎲 题库+错题 智能混编测试")
        st.caption("按 50% 到期错题 + 50% 题库新题 组卷，严格按考点去重防止同质化。")
        
        if st.button("🚀 生成今日 10 道专属试卷", type="primary"):
            if not df_errors.empty:
                pool = df_errors[df_errors["科目"] == selected_subject]
                
                if not pool.empty:
                    # 1. 从错题池抓取今天到期的题目 (优先)
                    due_pool = pool[(pool["来源"] == "错题") & (pool["NextReview"] <= datetime.today().date())]
                    due_samples = due_pool.drop_duplicates(subset=['考点标签']).sample(min(5, len(due_pool)))
                    
                    # 2. 从题库池抓取没做过的新题补足 (错误次数=0代表未激活)
                    bank_pool = pool[(pool["来源"] == "题库") & (pool["错误次数"] == 0) & (~pool["题目ID"].isin(due_samples["题目ID"]))]
                    bank_samples = bank_pool.drop_duplicates(subset=['考点标签']).sample(min(10 - len(due_samples), len(bank_pool)))
                    
                    quiz_df = pd.concat([due_samples, bank_samples]).sample(frac=1).reset_index(drop=True)
                    
                    st.markdown("---")
                    for idx, row in quiz_df.iterrows():
                        badge = "🔥 历史错题回顾" if row['来源'] == '错题' else "✨ 题库新题尝鲜"
                        with st.expander(f"题目 {idx+1} | 考点: {row['考点标签']} | {badge}"):
                            st.write(row['题目内容'])
                            
                            # 当你做错一道题库里的新题时，它可以一键转化为“错题”
                            if row['来源'] == '题库':
                                if st.button(f"😭 这道新题我做错了，转入错题本！", key=f"fail_{row['题目ID']}"):
                                    if supabase:
                                        # 将来源改为错题，错误次数+1，明天复习
                                        supabase.table("errors_table").update({"来源": "错题", "错误次数": 1, "StageInterval": 1, "NextReview": str(datetime.today().date() + timedelta(days=1))}).eq("题目ID", row['题目ID']).execute()
                                        st.rerun()
                else:
                    st.warning("该科目弹药库为空啦，先去录入或导入题库吧！")

# ------------------------------------------
# 右侧：私教伴学舱 (融入全量考点联动)
# ------------------------------------------
with col_right:
    st.subheader("🤖 核心推导私教舱")
    
    linkage_info = ""
    if st.session_state.current_focus_tag and not df_errors.empty:
        # 在整个题库(包含错题和题库新题)中寻找考点关联
        related_df = df_errors[(df_errors["考点标签"] == st.session_state.current_focus_tag) & (df_errors["题目ID"] != st.session_state.get('selected_q_id', ''))]
        if not related_df.empty:
            st.success(f"💡 **考点雷达响应：** 你在 `{st.session_state.current_focus_tag}` 考点上，总题库中还有 {len(related_df)} 道相关资源！")
            linkage_info = f"系统检索到学生题库中有此考点的储备。关联片段：{related_df.iloc[0]['题目内容'][:50]}..."

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): 
            st.markdown(msg["content"])

    if user_query := st.chat_input("请求公式推导、或输入你的做题思路求纠错..."):
        if st.session_state.chat_history[-1]["content"] != user_query:
            st.session_state.chat_history.append({"role": "user", "content": user_query})
            st.rerun()

    if st.session_state.chat_history[-1]["role"] == "user":
        user_msg = st.session_state.chat_history[-1]["content"]
        with st.chat_message("assistant"):
            with st.spinner("系统正在利用严密逻辑网进行推导排版..."):
                try:
                    context_prompt = (
                        f"你现在是一位严谨的考研国家线阅卷组专家级导师。\n"
                        f"请使用最规范的学术语言、严密的逻辑和教科书级别的推导过程解答。\n"
                        f"所有数学公式必须使用标准的 LaTeX 语法。\n"
                    )
                    if selected_subject: context_prompt += f"【当前科目】：{selected_subject}\n"
                    if st.session_state.current_focus_content: context_prompt += f"【当前攻坚题目】：\n{st.session_state.current_focus_content}\n"
                    if linkage_info: context_prompt += f"【系统提示导师】：{linkage_info}\n请在解答时进行知识点点拨。\n"
                    
                    context_prompt += f"\n学生提问：{user_msg}\n导师解答："
                    
                    res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=context_prompt)
                    st.session_state.chat_history.append({"role": "assistant", "content": res.text})
                    st.rerun()
                except Exception as e:
                    st.error(f"通讯中断: {e}")
