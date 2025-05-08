import streamlit as st
import requests
import fitz  # PyMuPDF
import os
import io
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload
from dotenv import load_dotenv
from googleapiclient.errors import HttpError
import json

# --- ページ設定とUI非表示 ---
st.set_page_config(
    page_title="業務分類QAボット (Drive連携)",
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

# --- 認証とAPIキー読み込み ---
load_dotenv()
API_KEY = os.getenv("API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={API_KEY}"

# --- Google Drive 認証 ---
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
info = st.secrets["service_account"]
credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

drive_service = build("drive", "v3", credentials=credentials)

# --- DriveからPDF一覧取得 ---
FOLDER_ID = "1l7ux1L_YCMHY1Jt-AlLci88Bh3Fcv_-m"  # ← あなたのフォルダID
query = f"'{FOLDER_ID}' in parents and mimeType='application/pdf'"

try:
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    pdf_files = results.get("files", [])
except HttpError as e:
    st.error(f"❌ Google Drive API エラーが発生しました：{e}")
    st.stop()

# --- テキスト抽出処理 ---
def extract_text_from_drive_pdf(file_id):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    doc = fitz.open(stream=fh.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

# --- 質問フォーム ---
with st.form("qa_form"):
    question = st.text_input("❓ 質問を入力してください", value=st.session_state.get("question", ""))
    submitted = st.form_submit_button("質問する")

    if submitted and question:
        st.session_state["question"] = question
        all_text = ""

        # --- スピナー表示 ---
        with st.spinner("🔍 質問に対する回答を準備中です..."):
            for file in pdf_files:
                file_id = file["id"]
                file_name = file["name"]
                try:
                    text = extract_text_from_drive_pdf(file_id)
                    all_text += f"\n--- {file_name} ---\n{text}\n"
                except Exception as e:
                    st.warning(f"{file_name} の読み込み中にエラーが発生しました: {e}")

            prompt = f"以下の社内文書を参考にして質問に答えてください。\n\n{all_text[:15000]}\n\nQ: {question}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            res = requests.post(GEMINI_URL, json=payload)

            if res.status_code == 200:
                st.session_state["answer"] = res.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                st.session_state["answer"] = f"❌ Gemini APIエラー: {res.status_code}"

# --- 回答表示 ---
if st.session_state.get("answer") and st.session_state.get("question"):
    st.markdown("### 回答：")
    st.write(st.session_state["answer"])

    if st.button(" クリア"):
        for key in ["question", "answer"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()
