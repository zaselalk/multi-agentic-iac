import os
import getpass
import logging
import sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from llama_index.llms.azure_inference import AzureAICompletionsModel
from llama_index.embeddings.azure_inference import AzureAIEmbeddingsModel
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.core import Settings
from llama_index.core import StorageContext, load_index_from_storage
from llama_index.core.node_parser import TokenTextSplitter
from azure.core.credentials import AzureKeyCredential

class Retriever:
    def __init__(self, stored_index = None, path = None):
        self.embed_model, self.llm = self.setup_api()
        self.index = self.retrieve_documents(stored_index, path)

    def setup_api(self):
        # Grounding runs through the same Azure AI Foundry project used for
        # generation (see evaluation/eval.py's foundry:<deployment-name>
        # models) - one endpoint/key, one embedding deployment for indexing,
        # and one chat deployment for this retriever's query generation.
        if "AZURE_AI_FOUNDRY_ENDPOINT" not in os.environ:
            endpoint = input("Enter Azure AI Foundry endpoint URL: ")
            os.environ["AZURE_AI_FOUNDRY_ENDPOINT"] = endpoint
        if "AZURE_AI_FOUNDRY_API_KEY" not in os.environ:
            api_key = getpass.getpass("Enter Azure AI Foundry API key: ")
            os.environ["AZURE_AI_FOUNDRY_API_KEY"] = api_key
        if "AZURE_AI_FOUNDRY_EMBEDDING_MODEL" not in os.environ:
            embedding_model = input("Enter Azure AI Foundry embedding deployment name (e.g. text-embedding-3-large): ")
            os.environ["AZURE_AI_FOUNDRY_EMBEDDING_MODEL"] = embedding_model
        if "AZURE_AI_FOUNDRY_RETRIEVER_MODEL" not in os.environ:
            retriever_model = input("Enter Azure AI Foundry chat deployment name for retrieval query generation (e.g. gpt-4.1-mini): ")
            os.environ["AZURE_AI_FOUNDRY_RETRIEVER_MODEL"] = retriever_model

        endpoint = os.environ["AZURE_AI_FOUNDRY_ENDPOINT"]
        credential = AzureKeyCredential(os.environ["AZURE_AI_FOUNDRY_API_KEY"])

        # azure-ai-inference defaults to api-version=2024-05-01-preview, which
        # not every Foundry deployment (e.g. Azure-OpenAI-family models
        # routed through Foundry) accepts. Let AZURE_AI_FOUNDRY_API_VERSION
        # override it when the deployment demands a specific version.
        client_kwargs = {}
        api_version = os.environ.get("AZURE_AI_FOUNDRY_API_VERSION")
        if api_version:
            client_kwargs["api_version"] = api_version

        embed_model = AzureAIEmbeddingsModel(
            endpoint=endpoint,
            credential=credential,
            model_name=os.environ["AZURE_AI_FOUNDRY_EMBEDDING_MODEL"],
            client_kwargs=client_kwargs,
        )

        llm = AzureAICompletionsModel(
            endpoint=endpoint,
            credential=credential,
            model_name=os.environ["AZURE_AI_FOUNDRY_RETRIEVER_MODEL"],
            client_kwargs=client_kwargs,
        )

        return embed_model, llm

    def retrieve_documents(self, stored_index = None, path = None):
        # if stored_index exists, load it
        Settings.llm = self.llm
        Settings.embed_model = self.embed_model
        if os.path.exists(stored_index):
            print("Loading index from storage")
            storage_context = StorageContext.from_defaults(persist_dir=stored_index)
            index = load_index_from_storage(storage_context)
        else: 
            print("Building index from scratch")
            nodes = self.read_docs(path)
            index = self.build_index(nodes)
            index.storage_context.persist(persist_dir=stored_index)
        return index 

    def read_docs(self, path = "terraform-provider-aws/website/docs/r"):
        
        documents = SimpleDirectoryReader(
            path
        ).load_data()

        # parser = MarkdownNodeParser()
        
        splitter = TokenTextSplitter(
            chunk_size=400,
            chunk_overlap=20,
            separator=" ",
        )
        nodes = splitter.get_nodes_from_documents(documents)
        print(f"Read {len(documents)} documents")
        print(f"Extracted {len(nodes)} nodes")
        return nodes

    def build_index(self, nodes):
        index = VectorStoreIndex(nodes)
        return index

    def generate_prompt_for_index(self, query, num_queries=10):
        # The prompt is not necessary 
        QUERY_GEN_PROMPT = (
            "You are a helpful assistant that generates multiple search queries based on a "
            "single input query. Generate {num_queries} search queries, one on each line, "
            "related to the following input query:\n"
            "Query: {query}\n"
        )
        formatted_prompt = QUERY_GEN_PROMPT.format(num_queries=num_queries, query=query)

        query_engine = self.index.as_query_engine()
        response = query_engine.query(formatted_prompt)
        questions = response.response.split('\n')

        print(questions) 
        return questions
 
    def query_documents(self, questions):
        retriever = self.index.as_retriever()

        context = set()
        for q in questions:
            if not isinstance(q, str) or q == "":
                continue
            nodes = retriever.retrieve(q)
            context.add(nodes[0].text)
        return context

if __name__ == "__main__":
    retriever = Retriever(stored_index='aws-index', path='terraform-provider-aws/website/docs/r')
    query = '''sets up a VPC with public and private subnets, multiple security groups for different components like master, worker, alert, API, standalone, and database services within an AWS region specified as "cn-north-1". It includes a 5.7, 50GB MySQL database instance within the VPC, accessible and secured by a designated security group.''' 
    questions = retriever.generate_prompt_for_index(query)
    # questions = ['defines an AWS RDS option group named "option-group-pike" with major engine version 11, and use the sqlserver-ee engine. It should have options for "SQLSERVER_AUDIT" and "TDE" ', '', '1. How to create an AWS RDS option group with major engine version 11 and sqlserver-ee engine?', '2. What are the available options for an AWS RDS option group with major engine version 11 and sqlserver-ee engine?', '3. How to add the "SQLSERVER_AUDIT" option to an AWS RDS option group?', '4. How to add the "TDE" option to an AWS RDS option group?', '5. What is the option group description for an AWS RDS option group named "option-group-pike"?', '6. How to set the timezone option for an AWS RDS option group?', '7. How to set the IAM role ARN for the "SQLSERVER_BACKUP_RESTORE" option in an AWS RDS option group?', '8. What are the MariaDB options available for an AWS RDS option group?', '9. What are the Microsoft SQL Server options available for an AWS RDS option group?', '10. What are the MySQL options available for an AWS RDS option group?'] # this caused an error
    context = retriever.query_documents(questions)
    for i, c in enumerate(context):
        print(f'Context {i}:')
        print(c)

    