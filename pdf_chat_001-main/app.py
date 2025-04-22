import streamlit as st
import requests
import fitz  # PyMuPDF
from dotenv import load_dotenv
import os

# --- ページ設定とUI非表示 ---
st.set_page_config(
    page_title="業務分類QAボット",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"Get Help": None, "Report a bug": None, "About": None}
)

# --- CSSでUI非表示 ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {display: none;}
    </style>
""", unsafe_allow_html=True)

# --- 環境変数の読み込み ---
load_dotenv()
API_KEY = os.getenv("API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={API_KEY}"

# --- PDFからテキスト抽出 ---
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

# --- Gemini API に質問 ---
def ask_gemini_about_pdf(text, question):
    prompt = f"以下の社内文書からこの質問に答えてください：\n\n{text[:4000]}\n\nQ: {question}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    res = requests.post(GEMINI_URL, json=payload)
    if res.status_code == 200:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    else:
        return f"❌ エラー: {res.status_code} - {res.text}"

# --- タイトル ---
st.title("📄 業務分類QAボット")

# --- セッション初期化（PDFは保持） ---
for key in ["question", "answer"]:
    if key not in st.session_state:
        st.session_state[key] = ""

# --- PDFを1回だけ読み込み ---
pdf_path = "sample.pdf"
if "pdf_text" not in st.session_state:
    try:
        st.session_state["pdf_text"] = extract_text_from_pdf(pdf_path)
    except Exception as e:
        st.error(f"PDFの読み込み中にエラーが発生しました：{e}")
        st.stop()

# --- フォーム（質問） ---
with st.form("qa_form"):
    question = st.text_input("質問を入力してください", value=st.session_state["question"])
    submitted = st.form_submit_button("💬 質問する")

    if submitted and question:
        st.session_state["question"] = question
        with st.spinner("⌛ 回答を考えています..."):
            st.session_state["answer"] = ask_gemini_about_pdf(
                st.session_state["pdf_text"], question
            )

# --- 回答表示（実行後のみ） ---
if st.session_state["answer"] and st.session_state["question"]:
    st.markdown("### 回答：")
    st.write(st.session_state["answer"])

    # --- ボタン列 ---
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🧹 回答クリア"):
            st.session_state["answer"] = ""
            st.rerun()

    with col2:
        if st.button("🔁 初期化（PDFは残す）"):
            for key in ["question", "answer"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
