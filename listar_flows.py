import requests
import json

r = requests.get('http://localhost:7860/api/v1/flows/', timeout=10)
flows = r.json()
print('Total de flows:', len(flows))
for i, f in enumerate(flows):
    print(f'{i+1}. {f["name"]} - ID: {f["id"]}')
