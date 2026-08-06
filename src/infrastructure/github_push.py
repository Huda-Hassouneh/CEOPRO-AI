import urllib.request
import json
import base64
import os

repo = 'Huda-Hassouneh/CEOPRO-AI'
user = input('Enter GitHub Username: ').strip()
pwd = input('Enter GitHub Password or Token: ').strip()

auth = base64.b64encode(f'{user}:{pwd}'.encode('utf-8')).decode('utf-8')
headers = {
    'Authorization': f'Basic {auth}',
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': 'Python'
}

def upload(path, local_path):
    try:
        if not os.path.exists(local_path):
            print(f"Skipping {path}: Local file not found.")
            return
        content = base64.b64encode(open(local_path, 'rb').read()).decode('utf-8')
        url = f'https://github.com{repo}/contents/{path}'
        
        # Check if file exists on GitHub to get SHA
        sha = ''
        try:
            req = urllib.request.Request(url, headers=headers)
            sha = json.loads(urllib.request.urlopen(req).read())['sha']
        except:
            pass
            
        data = {
            'message': f'feat(infra): production deployment of {os.path.basename(path)} core',
            'content': content,
            'branch': 'main'
        }
        if sha:
            data['sha'] = sha
            
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='PUT')
        urllib.request.urlopen(req)
        print(f'SUCCESSFULLY PUSHED: {path}')
    except Exception as e:
        print(f'Failed to push {path}: {e}')

# Execute uploads for core pipelines
upload('src/infrastructure/market_scraper.py', 'C:/Users/User/Desktop/ceopro-infra/src/infrastructure/market_scraper.py')
upload('src/infrastructure/init_broker.py', 'C:/Users/User/Desktop/ceopro-infra/src/infrastructure/init_broker.py')
upload('mocks/scraped_market_intelligence.json', 'C:/Users/User/Desktop/ceopro-infra/mocks/scraped_market_intelligence.json')

# Purge legacy target.txt file
url = f'https://github.com{repo}/contents/target.txt'
try:
    req = urllib.request.Request(url, headers=headers)
    res = json.loads(urllib.request.urlopen(req).read())
    data = {'message': 'chore(infra): purge legacy telemetry file', 'sha': res['sha'], 'branch': 'main'}
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='DELETE')
    urllib.request.urlopen(req)
    print('SUCCESSFULLY PURGED: target.txt')
except Exception as e:
    pass
