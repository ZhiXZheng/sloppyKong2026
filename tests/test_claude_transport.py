"""No-network coverage of actionable, sanitized Claude transport failures."""
import io
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

from person_b.ai_client import ClaudeAPIError, ClaudeProvider


@pytest.mark.parametrize('code,category,retryable',[
    (400,'invalid_request',False),(401,'authentication',False),
    (403,'permission',False),(404,'model_not_found',False),
    (408,'timeout',True),(429,'rate_limit',True),
    (500,'server_error',True),(529,'overloaded',True),
])
def test_http_error_metadata_never_contains_raw_api_body(code,category,retryable):
    provider=ClaudeProvider(api_key='private-test-key')
    error=HTTPError('https://api.anthropic.com/v1/messages',code,'error',
                    {'retry-after':'23'},io.BytesIO(b'{"error":{"message":"private-test-key"}}'))
    with patch('person_b.ai_client.urlopen',side_effect=error),pytest.raises(ClaudeAPIError) as caught:
        provider.generate('safe',12,{'type':'object'},'safe')
    assert caught.value.category==category
    assert caught.value.retryable==retryable
    assert caught.value.retry_after==23
    assert 'private-test-key' not in str(caught.value)


def test_spend_cap_does_not_schedule_useless_retries():
    provider=ClaudeProvider(api_key='test')
    body={'error':{'details':{'error_code':'enforced_spend_limit_reached'}}}
    error=HTTPError('https://api.anthropic.com/v1/messages',429,'error',{},io.BytesIO(json.dumps(body).encode()))
    with patch('person_b.ai_client.urlopen',side_effect=error),pytest.raises(ClaudeAPIError) as caught:
        provider.generate('safe',12,{'type':'object'},'safe')
    assert caught.value.category=='spend_limit'
    assert not caught.value.retryable


def test_socket_timeout_is_not_reported_as_validation_failure():
    provider=ClaudeProvider(api_key='test')
    with patch('person_b.ai_client.urlopen',side_effect=URLError(TimeoutError())),pytest.raises(ClaudeAPIError) as caught:
        provider.generate('safe',12,{'type':'object'},'safe')
    assert caught.value.category=='timeout'
    assert caught.value.retryable


class Response(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self,*args):
        self.close()


def response(stop='end_turn'):
    return Response(json.dumps(dict(stop_reason=stop,content=[dict(type='text',text='{}')],usage={})).encode())


def test_request_budget_is_explicit_and_prevents_network_calls():
    provider=ClaudeProvider(api_key='test',max_requests=1)
    with patch('person_b.ai_client.urlopen',return_value=response()) as http:
        provider.generate('safe',12,{'type':'object'},'safe')
        with pytest.raises(ClaudeAPIError) as caught:
            provider.generate('safe',12,{'type':'object'},'safe')
        assert caught.value.category=='request_budget_exhausted'
        assert not caught.value.retryable
        assert http.call_count==1


def test_truncated_output_is_identified_separately():
    provider=ClaudeProvider(api_key='test')
    with patch('person_b.ai_client.urlopen',return_value=response('max_tokens')),pytest.raises(ClaudeAPIError) as caught:
        provider.generate('safe',12,{'type':'object'},'safe')
    assert caught.value.category=='output_truncated'
    assert caught.value.retryable
