import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Input, Button, Slider, Loading, addToast } from '../../components/ui';
import apiClient from '../../api/client';
import { useAppStore } from '../../store/app';

export const APIConfigPage = () => {
  const { apiKey, setApiKey, setApiConfig } = useAppStore();
  const [config, setConfig] = useState({
    api_key: '',
    base_url: 'https://api.yunwu.ai/v1',
    model: 'gpt-4o-mini',
    temperature: 0.7,
    max_tokens: 2000,
    top_p: 1.0,
    frequency_penalty: 0.0,
    presence_penalty: 0.0,
  });

  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [formChanged, setFormChanged] = useState(false);
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [hasMaskedKey, setHasMaskedKey] = useState(false);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const response = await apiClient.getConfig();
      const serverConfig = response.data || {};
      const masked = typeof serverConfig.api_key === 'string' && serverConfig.api_key.includes('***');
      const storedKey = localStorage.getItem('apiKey') || '';
      const effectiveKey = storedKey || (masked ? '' : (serverConfig.api_key || ''));

      setHasMaskedKey(masked);
      setConfig({
        api_key: effectiveKey,
        base_url: serverConfig.base_url || 'https://api.yunwu.ai/v1',
        model: serverConfig.model || 'gpt-4o-mini',
        temperature: serverConfig.temperature ?? 0.7,
        max_tokens: serverConfig.max_tokens ?? 2000,
        top_p: serverConfig.top_p ?? 1.0,
        frequency_penalty: serverConfig.frequency_penalty ?? 0.0,
        presence_penalty: serverConfig.presence_penalty ?? 0.0,
      });

      if (effectiveKey) {
        setApiKey(effectiveKey);
      }
      
      // 更新完整的API配置到store
      setApiConfig({
        api_key: effectiveKey,
        base_url: serverConfig.base_url || 'https://api.yunwu.ai/v1',
        model: serverConfig.model || 'gpt-4o-mini',
        temperature: serverConfig.temperature ?? 0.7,
        max_tokens: serverConfig.max_tokens ?? 2000,
        top_p: serverConfig.top_p ?? 1.0,
        frequency_penalty: serverConfig.frequency_penalty ?? 0.0,
        presence_penalty: serverConfig.presence_penalty ?? 0.0,
      });
      
      setApiKeyDirty(false);
      setFormChanged(false);
      setLoading(false);
    } catch (error) {
      console.error('Failed to load config:', error);
      setLoading(false);
    }
  };

  const handleChange = (field: string, value: any) => {
    setConfig((prev) => ({
      ...prev,
      [field]: value,
    }));
    setFormChanged(true);
    if (field === 'api_key') {
      setApiKeyDirty(true);
    }
  };

  const handleSave = async () => {
    try {
      const payload: Record<string, any> = {
        base_url: config.base_url,
        model: config.model,
        temperature: config.temperature,
        max_tokens: config.max_tokens,
        top_p: config.top_p,
        frequency_penalty: config.frequency_penalty,
        presence_penalty: config.presence_penalty,
      };

      if (apiKeyDirty && config.api_key) {
        payload.api_key = config.api_key;
      }

      await apiClient.updateConfig(payload);
      setFormChanged(false);
      if (apiKeyDirty && config.api_key) {
        setApiKey(config.api_key);
        setApiKeyDirty(false);
      }
      
      // 更新store中的API配置
      setApiConfig({
        api_key: config.api_key,
        base_url: config.base_url,
        model: config.model,
        temperature: config.temperature,
        max_tokens: config.max_tokens,
        top_p: config.top_p,
        frequency_penalty: config.frequency_penalty,
        presence_penalty: config.presence_penalty,
      });
      
      addToast('配置已保存', 'success');
    } catch (error) {
      addToast('保存配置失败', 'error');
    }
  };

  const handleTestConnection = async () => {
    try {
      const keyToTest = config.api_key || apiKey;
      if (!keyToTest) {
        addToast('请先输入 API Key', 'error');
        return;
      }
      setTesting(true);
      const response = await apiClient.testOpenAIConnection({
        api_key: keyToTest,
        base_url: config.base_url,
        model: config.model,
      });
      
      // 检查响应的 success 字段
      if (response.data.success) {
        addToast('连接成功！', 'success');
      } else {
        addToast(`连接失败: ${response.data.message}`, 'error');
      }
    } catch (error) {
      addToast('连接失败，请检查API Key和配置', 'error');
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <Loading />;

  const keyHelper = hasMaskedKey && !config.api_key
    ? '已配置过 API Key（脱敏显示），如需修改请重新输入'
    : '你的OpenAI API密钥';

  const hasKey = Boolean(config.api_key || apiKey);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>OpenAI配置</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input
            label="API Key"
            type="password"
            value={config.api_key}
            onChange={(e) => handleChange('api_key', e.target.value)}
            placeholder="sk-..."
            helper={keyHelper}
          />

          <Input
            label="Base URL"
            value={config.base_url}
            onChange={(e) => handleChange('base_url', e.target.value)}
            placeholder="https://api.yunwu.ai/v1"
          />

          <Input
            label="Model"
            value={config.model}
            onChange={(e) => handleChange('model', e.target.value)}
            placeholder="gpt-4o-mini"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>高级参数</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <Slider
            label="Temperature (创意度)"
            min={0}
            max={2}
            step={0.1}
            value={config.temperature}
            onChange={(v) => handleChange('temperature', v)}
          />

          <Input
            label="Max Tokens (最大输出词数)"
            type="number"
            value={config.max_tokens}
            onChange={(e) => handleChange('max_tokens', parseInt(e.target.value))}
          />

          <Slider
            label="Top P"
            min={0}
            max={1}
            step={0.1}
            value={config.top_p}
            onChange={(v) => handleChange('top_p', v)}
          />

          <Slider
            label="Frequency Penalty"
            min={-2}
            max={2}
            step={0.1}
            value={config.frequency_penalty}
            onChange={(v) => handleChange('frequency_penalty', v)}
          />

          <Slider
            label="Presence Penalty"
            min={-2}
            max={2}
            step={0.1}
            value={config.presence_penalty}
            onChange={(v) => handleChange('presence_penalty', v)}
          />
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Button
          variant="primary"
          onClick={handleSave}
          disabled={!formChanged}
        >
          保存配置
        </Button>
        <Button
          variant="secondary"
          onClick={handleTestConnection}
          isLoading={testing}
          disabled={!hasKey}
        >
          测试连接
        </Button>
      </div>
    </div>
  );
};
