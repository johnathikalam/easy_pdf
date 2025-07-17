from flask import Flask, request, jsonify, render_template
import os
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

app = Flask(__name__)


# Initialize Pinecone
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index_name = os.environ.get("PINECONE_INDEX_NAME")
index = pc.Index(index_name)
embeddings = OpenAIEmbeddings(model="text-embedding-3-large", api_key=os.environ.get("OPENAI_API_KEY"))
vector_store = PineconeVectorStore(index=index, embedding=embeddings)

# Text Splitter
text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=400)

chat_history = [SystemMessage("You are an assistant for question-answering tasks.")]
use_external = True 

@app.route('/')
def home():
    return render_template('index.html')

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    os.makedirs("uploads", exist_ok=True)
    
    file_path = os.path.join("uploads", file.filename)
    file.save(file_path)

    # Load and process PDF
    try:
        loader = PyPDFLoader(file_path)
        raw_docs = loader.load()
        documents = text_splitter.split_documents(raw_docs)

        # Ensure documents are not empty
        if not documents:
            return jsonify({"error": "No text found in PDF."}), 400
        uuids = [f"id{i+1}" for i in range(len(documents))]
        # vector_store.add_documents(documents=documents, ids=uuids)
        batch_size = 50
        for doc_batch, id_batch in zip(chunk_list(documents, batch_size), chunk_list(uuids, batch_size)):
            vector_store.add_documents(documents=doc_batch, ids=id_batch)
        return jsonify({"message": "File uploaded and indexed successfully"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/clear', methods=['POST'])
def clear_vectors():
    index.delete(delete_all=True)
    return jsonify({"message": "All vectors deleted from Pinecone"})

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json.get("query")
    if not user_input:
        return jsonify({"error": "Query is required"}), 400
    
    chat_history.append(HumanMessage(user_input))
    
    retriever = vector_store.as_retriever(search_type="similarity_score_threshold", search_kwargs={"k": 3, "score_threshold": 0.5})
    docs = retriever.invoke(user_input)
    docs_text = "".join(d.page_content for d in docs)
    
    system_prompt = f"""
    You are an assistant for question-answering tasks.
    Use the following retrieved context to answer the question.
    If you don't know, say you don't know.
    Use three sentences max and keep it concise.
    Context: {docs_text} """
    
    chat_history.append(SystemMessage(system_prompt))
    llm = ChatOpenAI(model="gpt-4o", temperature=1)
    assistant_response = llm.invoke(chat_history).content
    chat_history.append(AIMessage(assistant_response))
    
    return jsonify({"response": assistant_response})

if __name__ == "__main__":
    app.run(debug=True)