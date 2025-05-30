# app.py
# 税理士事務所向け：Streamlit + Google Drive + Pinecone + Gemini を用いたPDF質問Bot

import os
import io
import fitz  # PyMuPDF
import streamlit as st
import pinecone
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings

# --- 初期設定 ---
st.set_page_config(page_title="税理士事務所向け PDF QA Bot", layout="wide")

# --- Secretsから読み込み ---
GEMINI_API_KEY = st.secrets["API_KEY"]
PINECONE_API_KEY = st.secrets["PINECONE_API_KEY"]
PINECONE_ENV = st.secrets["PINECONE_ENV"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
PDF_FOLDER_ID = st.secrets["PDF_FOLDER_ID"]

# --- Google 認証情報 ---
info = st.secrets["service_account"]
credentials = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
drive_service = build("drive", "v3", credentials=credentials)

# --- Pinecone 初期化 ---
pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
if "pdf-index" not in pinecone.list_indexes():
    pinecone.create_index("pdf-index", dimension=1536)
index = pinecone.Index("pdf-index")

# --- テキスト抽出 ---
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

# --- PDFのインデックス化 ---
def index_pdfs():
    results = drive_service.files().list(q=f"'{PDF_FOLDER_ID}' in parents and mimeType='application/pdf'", fields="files(id, name)").execute()
    files = results.get("files", [])
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    embedder = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    
    for file in files:
        file_id = file["id"]
        file_name = file["name"]
        text = extract_text_from_drive_pdf(file_id)
        if not text.strip():
            st.warning(f"⚠ 空のPDF ({file_name}) はスキップしました。")
            continue
        chunks = splitter.split_text(text)
        vectors = embedder.embed_documents(chunks)
        ids = [f"{file_name}-{i}" for i in range(len(chunks))]
        metadata = [{"text": chunk, "source": file_name} for chunk in chunks]
        index.upsert(vectors=zip(ids, vectors, metadata))

# --- Geminiで回答生成 ---
def query_gemini(context, question):
    prompt = f"""以下の税務関連資料に基づいて質問に答えてください:\n\n{context}\n\n質問: {question}"""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
    res = requests.post(url, json=payload)
    try:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception:
        return f"❌ Gemini APIのレスポンス解析に失敗しました: {res.text}"

# --- UI ---
st.title("🧾 税理士事務所向け PDF QA Bot")

if st.button("📥 DriveのPDFをインデックス化"):
    with st.spinner("PDFを読み込み、ベクトル化してPineconeに登録中..."):
        index_pdfs()
        st.success("✅ インデックス化が完了しました")

question = st.text_input("❓ 質問を入力してください（例：『昨年度の法人税申告書の控除額は？』）")

if question:
    embedder = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    query_vector = embedder.embed_query(question)
    results = index.query(vector=query_vector, top_k=5, include_metadata=True)
    context_chunks = results.get("matches", [])
    if not context_chunks:
        st.error("🔍 関連する情報が見つかりませんでした。")
    else:
        context = "\n".join([match["metadata"]["text"] for match in context_chunks])
        with st.spinner("💬 Geminiに問い合わせ中..."):
            answer = query_gemini(context, question)
            st.markdown("### 🧠 回答")
            st.write(answer)
            with st.expander("📚 参照された資料の一部"):
                for match in context_chunks:
                    st.markdown(f"📄 **{match['metadata']['source']}** より:\n\n{match['metadata']['text'][:500]}...")
