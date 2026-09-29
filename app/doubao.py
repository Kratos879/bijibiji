"""Doubao Seed ASR 2.0 adapter; credentials never appear in errors."""
import base64
import json
import time
import uuid
import httpx

BASE = 'https://openspeech.bytedance.com/api/v3/auc/bigmodel'
RESOURCE = 'volc.seedasr.auc'

def transcribe_file(audio, config, check=lambda: None):
    token = config.get('api_key', '')
    if not token:
        raise ValueError('请在语音设置中填写豆包语音 API Key 或 Access Token')
    mode = config.get('auth_mode', 'api_key')
    if mode == 'app_token' and not config.get('app_id'):
        raise ValueError('请填写豆包语音控制台的 APP ID')
    headers = {'X-Api-Resource-Id': RESOURCE, 'X-Api-Sequence': '-1'}
    if mode == 'app_token':
        headers.update({'X-Api-App-Key': config['app_id'], 'X-Api-Access-Key': token})
    else:
        headers['X-Api-Key'] = token
    # Persist the accepted request id, so continuing a paused job does not submit twice.
    state_path = audio.with_suffix('.doubao-task.json')
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    def status(response):
        if response.status_code in (401, 403):
            raise ValueError('豆包认证或权限失败：请使用豆包语音服务的凭证，并开通录音文件识别 2.0')
        if response.status_code >= 400:
            raise ValueError(f'豆包转写请求失败（HTTP {response.status_code}），请检查语音服务是否开通')
        code = response.headers.get('X-Api-Status-Code', '')
        if code not in ('20000000', '20000001', '20000002'):
            if code == '20000003': raise ValueError('豆包未检测到可识别的语音')
            raise ValueError(f'豆包转写失败（状态码 {code if code.isdigit() else "未知"}），请检查凭证、2.0 权限及音频格式')
        return code
    with httpx.Client(timeout=httpx.Timeout(180, connect=20)) as client:
        if not state:
            check()
            request_id = str(uuid.uuid4())
            headers['X-Api-Request-Id'] = request_id
            body = {'user': {'uid': 'bijibiji'},
                    'audio': {'data': base64.b64encode(audio.read_bytes()).decode(), 'format': 'mp3'},
                    'request': {'model_name': 'bigmodel', 'enable_itn': True,
                                'enable_punc': True, 'show_utterances': True}}
            response = client.post(BASE + '/submit', headers=headers, json=body)
            status(response)
            state = {'request_id': request_id}
            state_path.write_text(json.dumps(state))
        headers['X-Api-Request-Id'] = state['request_id']
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            check()
            response = client.post(BASE + '/query', headers=headers, json={})
            code = status(response)
            if code == '20000000':
                result = response.json().get('result', {})
                segments = [{'start': u['start_time']/1000, 'end': u['end_time']/1000, 'text': u['text']}
                            for u in result.get('utterances', []) if u.get('text')]
                if not segments and not result.get('text'):
                    raise ValueError('豆包识别完成，但未返回文字')
                return {'text': result.get('text', ''), 'segments': segments}
            for _ in range(3):
                check(); time.sleep(1)
    raise ValueError('豆包仍在处理音频，请稍后点击继续处理；已保留任务，无需重新提交')
