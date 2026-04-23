import urllib.request
import json
import time

data = json.dumps({
    'userRequest': {'user': {'id': 'test_user'}, 'utterance': 'https://www.youtube.com/watch?v=PWoOTBP7JGw 나중에 이 영상 볼거니까 대충 어떤 영상인지 간단히 요약해줘'},
    'action': {'name': 'test'}
}).encode('utf-8')

req = urllib.request.Request('http://localhost:8000/api/v1/chat/webhook', data=data, headers={'Content-Type': 'application/json'})

start_time = time.time()
resp = urllib.request.urlopen(req)
end_time = time.time()

print(f'[SUCCESS] 응답 시간 (서버 지연시간): {end_time - start_time:.4f} 초')
print(f'[SUCCESS] 받은 데이터: {resp.read().decode("utf-8")}')
