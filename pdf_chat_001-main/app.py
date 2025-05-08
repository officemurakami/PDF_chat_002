import streamlit as st
import requests
import fitz  # PyMuPDF
import os
import io
import json
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

# --- 認証とAPIキー読み込み ---
load_dotenv()
API_KEY = os.getenv("API_KEY") or st.secrets["API_KEY"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={API_KEY}"

# --- Google Drive 認証（secrets.tomlから読込） ---
SERVICE_ACCOUNT_INFO = st.secrets["service_account"]
credentials = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO)
drive_service = build("drive", "v3", credentials=credentials)

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
        return f"\u274c エラー: {res.status_code} - {res.text}"
from googleapiclient.errors import HttpError  # ← ファイルの上部（import群）に追加されていない場合はここも忘れずに！

# --- DriveからPDF一覧取得 ---
FOLDER_ID = "1l7ux1L_YCMHY1Jt-AlLci88Bh3Fcv_-m"  # ★DriveのフォルダIDをここに設定
query = f"'{FOLDER_ID}' in parents and mimeType='application/pdf'"

try:
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    pdf_files = results.get("files", [])
except HttpError as e:
    st.error(f"❌ Google Drive API エラーが発生しました：{e}")
    st.stop()

file_names = [f["name"] for f in pdf_files]
selected_name = st.selectbox("📂 Google DriveのPDFファイルを選択", file_names)
names)

# --- ダウンロード関数 ---
def download_pdf_from_drive(file_id, save_path):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.FileIO(save_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

# --- 選択ファイル取得 ---
selected_file = next(f for f in pdf_files if f["name"] == selected_name)
local_pdf_path = f"/tmp/{selected_file['name']}"
if "pdf_text" not in st.session_state or st.session_state.get("last_file") != selected_name:
    download_pdf_from_drive(selected_file["id"], local_pdf_path)
    st.session_state["pdf_text"] = extract_text_from_pdf(local_pdf_path)
    st.session_state["last_file"] = selected_name

# --- セッション初期化（PDFは保持） ---
for key in ["question", "answer"]:
    if key not in st.session_state:
        st.session_state[key] = ""

# --- フォーム（質問） ---
with st.form("qa_form"):
    question = st.text_input("質問を入力してください", value=st.session_state["question"])
    submitted = st.form_submit_button("\ud83d\udcac 質問する")

    if submitted and question:
        st.session_state["question"] = question
        with st.spinner("\u231b 回答を考えています..."):
            st.session_state["answer"] = ask_gemini_about_pdf(
                st.session_state["pdf_text"], question
            )

# --- 回答表示 ---
if st.session_state["answer"] and st.session_state["question"]:
    st.markdown("### 回答：")
    st.write(st.session_state["answer"])
    col1, col2 = st.columns(2)
    with col1:
        if st.button("\ud83e\ude79 回答クリア"):
            st.session_state["answer"] = ""
            st.rerun()
    with col2:
        if st.button("\ud83d\udd01 初期化（PDFは残す）"):
            for key in ["question", "answer"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
