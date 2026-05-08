from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os

load_dotenv("/Volumes/Meet/Projects/Salesforce/agentdesk/.env")

sf = Salesforce(
    username=os.getenv("SALESFORCE_USERNAME"),
    password=os.getenv("SALESFORCE_PASSWORD"),
    security_token=os.getenv("SALESFORCE_SECURITY_TOKEN"),
    domain=os.getenv("SALESFORCE_DOMAIN", "login"),
)

print(sf.sf_instance)