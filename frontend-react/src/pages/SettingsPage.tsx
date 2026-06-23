import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { getCompanyConfig, saveCompanyConfig } from '../api/client';
import type { CompanyConfig } from '../types';
import { CompanyMasterPanel } from '../components/CompanyMaster/CompanyMasterPanel';

type SettingsTab = 'config' | 'companies';

export const SettingsPage: React.FC = () => {
  const [tab, setTab] = useState<SettingsTab>('config');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CompanyConfig>();

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    setError(null);

    try {
      const config = await getCompanyConfig();
      reset(config);
    } catch (err) {
      setError(err instanceof Error ? err.message : '設定の読み込みに失敗しました');
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = async (data: CompanyConfig) => {
    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await saveCompanyConfig(data);
      setSuccess(result.message);

      // 設定を再読み込み
      await loadConfig();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存に失敗しました');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-6">⚙️ 設定</h1>

      {/* タブバー */}
      <div className="flex gap-1 border-b border-gray-200 mb-6">
        <button
          onClick={() => setTab('config')}
          className={`px-5 py-3 font-semibold text-sm border-b-2 transition-colors ${
            tab === 'config'
              ? 'border-primary text-primary'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          自社情報
        </button>
        <button
          onClick={() => setTab('companies')}
          className={`px-5 py-3 font-semibold text-sm border-b-2 transition-colors ${
            tab === 'companies'
              ? 'border-primary text-primary'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          得意先・仕入先マスタ
        </button>
      </div>

      {tab === 'companies' ? (
        <CompanyMasterPanel />
      ) : loading ? (
        <div className="flex justify-center items-center py-20">
          <Spinner message="設定を読み込み中..." />
        </div>
      ) : (
        <>
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
            <p className="text-gray-700 leading-relaxed">
              請求書PDFに記載される自社情報を設定できます。
              <br />
              設定は <code className="bg-gray-200 px-1 rounded">company_config.json</code>{' '}
              に保存され、即座に反映されます。
            </p>
          </div>

          {error && (
            <Message type="error" className="mb-4">
              {error}
            </Message>
          )}

          {success && (
            <Message type="success" className="mb-4">
              {success}
              <br />
              💡 変更は次回のPDF生成から反映されます
            </Message>
          )}

          <form onSubmit={handleSubmit(onSubmit)}>
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-2xl font-semibold text-gray-700 mb-6">📝 自社情報</h2>

          <div className="space-y-6">
            {/* 適格請求書発行事業者登録番号 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                適格請求書発行事業者登録番号
                {errors.registration_number && (
                  <span className="text-red-500 ml-2 text-xs">
                    {errors.registration_number.message}
                  </span>
                )}
              </label>
              <input
                type="text"
                {...register('registration_number', {
                  required: '登録番号は必須です',
                })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="例: T1234567890123"
              />
              <p className="text-xs text-gray-500 mt-1">
                例: T1234567890123
              </p>
            </div>

            {/* 会社名 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                会社名
                {errors.company_name && (
                  <span className="text-red-500 ml-2 text-xs">
                    {errors.company_name.message}
                  </span>
                )}
              </label>
              <input
                type="text"
                {...register('company_name', {
                  required: '会社名は必須です',
                })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="例: 株式会社サンプル"
              />
              <p className="text-xs text-gray-500 mt-1">
                例: 株式会社サンプル
              </p>
            </div>

            {/* 郵便番号 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                郵便番号
                {errors.postal_code && (
                  <span className="text-red-500 ml-2 text-xs">
                    {errors.postal_code.message}
                  </span>
                )}
              </label>
              <input
                type="text"
                {...register('postal_code', {
                  required: '郵便番号は必須です',
                })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="例: 123-4567"
              />
              <p className="text-xs text-gray-500 mt-1">
                例: 123-4567
              </p>
            </div>

            {/* 住所 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                住所
                {errors.address && (
                  <span className="text-red-500 ml-2 text-xs">
                    {errors.address.message}
                  </span>
                )}
              </label>
              <input
                type="text"
                {...register('address', {
                  required: '住所は必須です',
                })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="例: 東京都千代田区〇〇1-2-3"
              />
              <p className="text-xs text-gray-500 mt-1">
                例: 東京都千代田区〇〇1-2-3
              </p>
            </div>

            {/* 電話番号 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                電話番号
                {errors.phone && (
                  <span className="text-red-500 ml-2 text-xs">
                    {errors.phone.message}
                  </span>
                )}
              </label>
              <input
                type="text"
                {...register('phone', {
                  required: '電話番号は必須です',
                })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="例: 03-1234-5678"
              />
              <p className="text-xs text-gray-500 mt-1">
                例: 03-1234-5678
              </p>
            </div>

            {/* 銀行口座情報 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                銀行口座情報
                {errors.bank_info && (
                  <span className="text-red-500 ml-2 text-xs">
                    {errors.bank_info.message}
                  </span>
                )}
              </label>
              <input
                type="text"
                {...register('bank_info', {
                  required: '銀行口座情報は必須です',
                })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="例: 〇〇銀行 △△支店 普通 1234567"
              />
              <p className="text-xs text-gray-500 mt-1">
                例: 〇〇銀行 △△支店 普通 1234567
              </p>
            </div>
          </div>

          <div className="mt-8">
            <Button
              type="submit"
              variant="primary"
              fullWidth
              loading={submitting}
            >
              💾 保存
            </Button>
          </div>
        </div>
      </form>
        </>
      )}
    </div>
  );
};
