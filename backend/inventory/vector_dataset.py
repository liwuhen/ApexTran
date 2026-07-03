from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores.pgvector import DistanceStrategy, PGVector
from langchain_core.documents import Document


class LLMDataset:
    def __init__(self):
        self.db = None

    def set_client(
        self,
        host: str = "localhost",
        port: str = "5432",
        user: str = "postgres",
        password: str = "",
        dbname: str = "postgres",
    ):

        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.connection_string = (
            f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"
        )

        return self.connection_string

    def get_pgvector(
        self,
        docs: list[Document],
        embeddings: DashScopeEmbeddings,
        collection_name: str,
        connection_string: str,
        distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
        pre_delete_collection: bool = True,
    ) -> PGVector:

        self.db = PGVector.from_documents(
            documents=docs,
            embedding=embeddings,
            collection_name=collection_name,
            distance_strategy=distance_strategy,
            pre_delete_collection=pre_delete_collection,
            connection_string=connection_string,
        )
        return self.db
