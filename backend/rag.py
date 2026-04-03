"""
rag.py  –  Lightweight RAG using ChromaDB (local, no API needed)
           Loads mock HomeFirst policy FAQs and retrieves relevant context.
"""

import chromadb
from chromadb.utils import embedding_functions

# ── Mock Policy Documents (HomeFirst-style FAQs) ────────────────────────────
POLICY_DOCS = [
    {
        "id": "doc_001",
        "content": (
            "HomeFirst Finance offers home loans starting from ₹2 lakh to ₹75 lakh. "
            "The minimum loan amount is ₹2 lakh and maximum is ₹75 lakh. "
            "Loan tenure ranges from 1 year to 30 years."
        ),
        "metadata": {"topic": "loan_amount"},
    },
    {
        "id": "doc_002",
        "content": (
            "Documents required for salaried applicants: "
            "1) KYC documents (Aadhaar, PAN card). "
            "2) Last 3 months salary slips. "
            "3) Last 6 months bank statement. "
            "4) Form 16 or ITR for last 2 years. "
            "5) Property documents (sale agreement, title deed)."
        ),
        "metadata": {"topic": "documents_salaried"},
    },
    {
        "id": "doc_003",
        "content": (
            "Documents required for self-employed applicants: "
            "1) KYC documents (Aadhaar, PAN card). "
            "2) ITR with computation for last 2-3 years. "
            "3) Last 12 months bank statement (business and personal). "
            "4) Business proof (GST certificate, trade license, or Udyam certificate). "
            "5) Property documents."
        ),
        "metadata": {"topic": "documents_self_employed"},
    },
    {
        "id": "doc_004",
        "content": (
            "HomeFirst Finance interest rates start from 8.75% per annum. "
            "Rates are linked to RPLR (Retail Prime Lending Rate). "
            "Both fixed and floating rate options are available. "
            "Processing fee is up to 3% of the loan amount plus GST."
        ),
        "metadata": {"topic": "interest_rates"},
    },
    {
        "id": "doc_005",
        "content": (
            "HomeFirst caters to the affordable housing segment and EWS/LIG categories. "
            "PMAY (Pradhan Mantri Awas Yojana) subsidy is available for eligible borrowers. "
            "Under PMAY, households with annual income up to ₹18 lakh can get interest subsidy of 3-6.5%."
        ),
        "metadata": {"topic": "pmay_subsidy"},
    },
    {
        "id": "doc_006",
        "content": (
            "FOIR (Fixed Obligation to Income Ratio) cap is 50% of net monthly income. "
            "LTV (Loan to Value) ratio: up to 90% for loans ≤₹30 lakh, "
            "up to 80% for loans between ₹30L-₹75L, up to 75% for loans above ₹75L. "
            "Minimum credit score required is 650 (CIBIL)."
        ),
        "metadata": {"topic": "eligibility_criteria"},
    },
    {
        "id": "doc_007",
        "content": (
            "HomeFirst Finance primarily focuses on FIRST-TIME home buyers in Tier 2 and Tier 3 cities. "
            "Target customers are from the informal sector, daily wage workers, and small business owners. "
            "Doorstep service and vernacular language support is available in Hindi, Marathi, Tamil, and other languages."
        ),
        "metadata": {"topic": "target_customers"},
    },
    {
        "id": "doc_008",
        "content": (
            "Home loan balance transfer is available at HomeFirst Finance. "
            "You can transfer your existing home loan from another bank to HomeFirst for better rates. "
            "Top-up loan facility is available for existing customers up to 100% of the original loan amount."
        ),
        "metadata": {"topic": "balance_transfer"},
    },
    {
        "id": "doc_009",
        "content": (
            "Prepayment and foreclosure: No prepayment penalty for floating rate loans as per RBI guidelines. "
            "For fixed rate loans, a foreclosure charge of 2% may apply. "
            "Part prepayment can be done anytime after 6 EMIs are paid."
        ),
        "metadata": {"topic": "prepayment"},
    },
    {
        "id": "doc_010",
        "content": (
            "Technical and legal verification: HomeFirst conducts a technical valuation of the property "
            "and a legal title search. Approved builder projects get faster processing. "
            "Under-construction properties: loan is disbursed in stages linked to construction progress. "
            "Ready-to-move properties get full disbursement."
        ),
        "metadata": {"topic": "property_verification"},
    },
]


class RAGSystem:
    """Simple RAG using ChromaDB with sentence-transformers embeddings (local, free)."""

    def __init__(self):
        self.client = chromadb.Client()
        self.ef = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name="homefirst_policies",
            embedding_function=self.ef,
        )
        self._load_documents()

    def _load_documents(self):
        """Load policy documents into ChromaDB (idempotent)."""
        existing_ids = set(self.collection.get()["ids"])
        new_docs = [d for d in POLICY_DOCS if d["id"] not in existing_ids]
        if new_docs:
            self.collection.add(
                ids=[d["id"] for d in new_docs],
                documents=[d["content"] for d in new_docs],
                metadatas=[d["metadata"] for d in new_docs],
            )

    def retrieve(self, query: str, n_results: int = 3) -> str:
        """
        Retrieve top-n relevant policy snippets for a user query.
        Returns a formatted string to inject into the LLM prompt.
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
        )
        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
        context = "\n\n".join(f"[Policy Context {i+1}]: {doc}" for i, doc in enumerate(docs))
        return context
