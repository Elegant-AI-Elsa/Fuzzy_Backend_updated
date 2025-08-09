from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatGoogleGenerativeAI
from langchain.text_splitter import RecursiveCharacterTextSplitter
from db_setup import get_vectorstore

# Set up the Gemini Flash model
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")

# Custom QA prompt (no links or sources shown to users)
prompt_template = """
You are a helpful assistant. Use the following context to answer the question.
Keep the answer clean, concise, and professional. Do not include any URLs or sources.

Context:
{context}

Question: {question}

Answer:
"""
prompt = PromptTemplate.from_template(prompt_template)

# Build QA chain with Retriever
def get_qa_chain():
    vectorstore = get_vectorstore()
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt},
        return_source_documents=False
    )

# Split and embed documents into the vectorstore
def train_on_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    docs = []
    for item in documents:
        text = item['content']
        metadata = {"url": item['url']}  # Store source for potential future use
        splits = splitter.create_documents([text], metadatas=[metadata])
        docs.extend(splits)

    vectorstore = get_vectorstore()
    vectorstore.add_documents(docs)
