# app.py
# Streamlit + Pinecone + OpenAI + Gemini を使ったPDF質問Bot（Google Drive連携）

import os
import io
import fitz
import streamlit as st
import pinecone
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings

# --- 初期設定 ---
st.set_page_config(page_title="PDF QA Bot", layout="wide")

# --- Secretsから読み込み ---
GEMINI_API_KEY = st.secrets["API_KEY"]
PINECONE_API_KEY = st.secrets["PINECONE_API_KEY"]
PINECONE_ENV = st.secrets["PINECONE_ENV"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
PDF_FOLDER_ID = st.secrets["PDF_FOLDER_ID"]

# --- Google 認証情報（Secretsのservice_accountから取得） ---
info = {
    "type": st.secrets["service_account"]["type"],
    "project_id": st.secrets["service_account"]["project_id"],
    "private_key_id": st.secrets["service_account"]["private_key_id"],
    "private_key": st.secrets["service_account"]["private_key"],
    "client_email": st.secrets["service_account"]["client_email"],
    "client_id": st.secrets["service_account"]["client_id"],
    "auth_uri": st.secrets["service_account"]["auth_uri"],
    "token_uri": st.secrets["service_account"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["service_account"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["service_account"]["client_x509_cert_url"]
}
credentials = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
drive_service = build("drive", "v3", credentials=credentials)

# --- Pinecone 初期化 ---
pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)

if "pdf-index" not in pinecone.list_indexes():
    pinecone.create_index("pdf-index", dimension=1536)

index = pinecone.Index("pdf-index")

# --- テキスト抽出関数（Drive PDF） ---
def extract_text_from_drive_pdf(file_id):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    doc = fitz.open(stream=fh.read(), filetype="pdf")
    return "\n".join([page.get_text() for page in doc])

# --- PDFのベクトル化＆Pinecone登録 ---
def index_pdfs():
    results = drive_service.files().list(q=f"'{PDF_FOLDER_ID}' in parents and mimeType='application/pdf'", fields="files(id, name)").execute()
    files = results.get("files", [])
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    embedder = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)

    for file in files:
        text = extract_text_from_drive_pdf(file["id"])
        if not text.strip():
            st.warning(f"⚠ 空のPDF ({file['name']}) はスキップしました。")
            continue
        chunks = splitter.split_text(text)
        vectors = embedder.embed_documents(chunks)
        ids = [f"{file['name']}-{i}" for i in range(len(chunks))]
        metadata = [{"text": chunk, "source": file["name"]} for chunk in chunks]
        index.upsert(zip(ids, vectors, metadata))

# --- Geminiで回答生成 ---
def query_gemini(context, question):
    prompt = f"""以下の情報に基づいて質問に答えてください:\n\n{context}\n\n質問: {question}"""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
    res = requests.post(url, json=payload)
    try:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception:
        return f"❌ Gemini APIのレスポンス解析に失敗しました: {res.text}"

# --- UI ---
st.title("📄 PDF Drive QA Bot (Pinecone連携)")

if st.button("📥 Drive内のPDFをインデックス化"):
    with st.spinner("PDFを読み込み、ベクトル化してPineconeに登録中..."):
        index_pdfs()
        st.success("✅ インデックス化完了")

question = st.text_input("❓ 質問を入力してください")
if question:
    embedder = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    query_vector = embedder.embed_query(question)
    results = index.query(vector=query_vector, top_k=5, include_metadata=True)
    context = "\n".join([match['metadata']['text'] for match in results['matches']])
    with st.spinner("💬 Geminiに問い合わせ中..."):
        answer = query_gemini(context, question)
        st.markdown("### 回答")
        st.write(answer)
