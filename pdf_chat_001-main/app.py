
import streamlit as st
import requests
import fitz  # PyMuPDF
import os
import io
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload
from dotenv import load_dotenv

# --- ページ設定とUI非表示 ---
st.set_page_config(
    page_title="業務分類QAボット（Drive連携）",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"Get Help": None, "Report a bug": None, "About": None}
)

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {display: none;}
    </style>
""", unsafe_allow_html=True)

# --- 認証とAPIキー ---
load_dotenv()
API_KEY = os.getenv("API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={API_KEY}"

# --- Google Drive 認証 ---
SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=credentials)

# --- DriveからPDF一覧取得 ---
FOLDER_ID = "1l7ux1L_YCMHY1Jt-ALlci88Bh3Fcv_-m"  # ご自身のフォルダID
query = f"'{FOLDER_ID}' in parents and mimeType='application/pdf'"
try:
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    pdf_files = results.get("files", [])
except requests.exceptions.RequestException as e:
    st.error(f"❌ Google Drive API エラー: {e}")
    st.stop()

# --- PDFファイルすべてを読み込んでテキスト化 ---
all_text = ""
for file in pdf_files:
    file_id = file["id"]
    request = drive_service.files().get_media(fileId=file_id)
    with io.BytesIO() as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        doc = fitz.open("pdf", fh.read())
        for page in doc:
            all_text += page.get_text()

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

# --- 質問フォーム ---
for key in ["question", "answer"]:
    if key not in st.session_state:
        st.session_state[key] = ""

with st.form("qa_form"):
    question = st.text_input("❓ 質問を入力してください", value=st.session_state["question"])
    submitted = st.form_submit_button("質問する")

    if submitted and question:
        st.session_state["question"] = question
        with st.spinner("⌛ 回答を考えています..."):
            st.session_state["answer"] = ask_gemini_about_pdf(all_text, question)

# --- 回答表示 ---
if st.session_state["answer"] and st.session_state["question"]:
    st.markdown("### 回答：")
    st.write(st.session_state["answer"])

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
