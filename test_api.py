import requests
import os
import time

# 禁用代理以防 503 错误
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

def test_analyze():
    url = "http://127.0.0.1:8000/api/v1/analyze"
    audio_file_path = "/Users/qc/Desktop/02_开发编程/AI_Coding/cherry/五羊讲解.mp3"
    
    if not os.path.exists(audio_file_path):
        print(f"Error: Audio file not found at {audio_file_path}")
        return

    print(f"Testing with file: {audio_file_path}")
    
    with open(audio_file_path, "rb") as f:
        files = {"file": (os.path.basename(audio_file_path), f, "audio/mpeg")}
        try:
            print("Sending request to /api/v1/analyze...")
            start_time = time.time()
            response = requests.post(url, files=files, timeout=300)
            end_time = time.time()
            
            print(f"Request took {end_time - start_time:.2f} seconds")
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("Result:")
                import json
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"Error Response: {response.text}")
                
        except Exception as e:
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    test_analyze()
