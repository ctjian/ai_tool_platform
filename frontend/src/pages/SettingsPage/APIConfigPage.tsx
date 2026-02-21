import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Input, Button, Slider, Loading, addToast } from '../../components/ui';
import apiClient from '../../api/client';
import { useAppStore } from '../../store/app';

export const APIConfigPage = () => {
  const { setApiConfig } = useAppStore();
    const [config, setConfig] = useState({
      temperature: 0.7,
      max_tokens: 2000,
    top_p: 1.0,
    frequency_penalty: 0.0,
    presence_penalty: 0.0,
  });

  const [loading, setLoading] = useState(true);
  const [formChanged, setFormChanged] = useState(false);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const response = await apiClient.getConfig();
      const serverConfig = response.data || {};
      setConfig({
        temperature: serverConfig.temperature ?? 0.7,
        max_tokens: serverConfig.max_tokens ?? 2000,
        top_p: serverConfig.top_p ?? 1.0,
        frequency_penalty: serverConfig.frequency_penalty ?? 0.0,
        presence_penalty: serverConfig.presence_penalty ?? 0.0,
      });

      // 更新完整的API配置到store
      setApiConfig({
        temperature: serverConfig.temperature ?? 0.7,
        max_tokens: serverConfig.max_tokens ?? 2000,
        top_p: serverConfig.top_p ?? 1.0,
        frequency_penalty: serverConfig.frequency_penalty ?? 0.0,
        presence_penalty: serverConfig.presence_penalty ?? 0.0,
      });
      
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
  };

  const handleSave = async () => {
    try {
      const payload: Record<string, any> = {
        temperature: config.temperature,
        max_tokens: config.max_tokens,
        top_p: config.top_p,
        frequency_penalty: config.frequency_penalty,
        presence_penalty: config.presence_penalty,
      };

      await apiClient.updateConfig(payload);
      setFormChanged(false);
      
      // 更新store中的API配置
      setApiConfig({
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

  if (loading) return <Loading />;

  return (
    <div className="space-y-6">
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
      </div>
    </div>
  );
};
