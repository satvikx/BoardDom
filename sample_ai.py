import os 
from openai import OpenAI
import httpx

client = OpenAI(
    api_key='',
    base_url='https://genailab.tcs.in/',
    http_client=httpx.Client(verify=False)
)

response = client.responses.create(
    model='genailab-openai-gpt-5.6-luna',
    input='Hiii Broo'
)

print('Response ID: ', response.id)
print('Output: ', response.output)