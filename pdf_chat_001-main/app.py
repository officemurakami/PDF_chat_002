# pinecone_pdf_bot.py
# Streamlit + Pinecone + OpenAI + Gemini を使ったPDF質問Bot（Google Drive連携）

import os
import io
import fitz
import streamlit as st
import pinecone
import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings

# --- 初期設定 ---
load_dotenv()
st.set_page_config(page_title="PDF QA Bot", layout="wide")

# --- APIキーなどの読み込み ---
GEMINI_API_KEY = os.getenv("API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV = os.getenv("PINECONE_ENV", "gcp-starter")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FOLDER_ID = os.getenv("PDF_FOLDER_ID")

# --- Google Drive 認証 ---
info = {
    "type": os.getenv("TYPE"),
    "project_id": os.getenv("PROJECT_ID"),
    "private_key_id": os.getenv("PRIVATE_KEY_ID"),
    "private_key": os.getenv("PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("CLIENT_EMAIL"),
    "client_id": os.getenv("CLIENT_ID"),
    "auth_uri": os.getenv("AUTH_URI"),
    "token_uri": os.getenv("TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL")
}
credentials = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
drive_service = build("drive", "v3", credentials=credentials)

# --- Pinecone 初期化 ---
pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
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
    results = drive_service.files().list(q=f"'{FOLDER_ID}' in parents and mimeType='application/pdf'", fields="files(id, name)").execute()
    files = results.get("files", [])
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    embedder = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)

    for file in files:
        text = extract_text_from_drive_pdf(file["id"])
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
    if res.status_code == 200:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    else:
        return f"❌ Gemini APIエラー: {res.status_code}"

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
