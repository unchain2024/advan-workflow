import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '../Common/Button';
import { Message } from '../Common/Message';
import { Spinner } from '../Common/Spinner';
import {
  listCompanyMaster,
  createCompanyMaster,
  updateCompanyMaster,
  deactivateCompanyMaster,
} from '../../api/client';
import type { CompanyDomain, CompanyMasterItem } from '../../types';

// 課税区分の選択肢（仕入のみ）。null=自動判定（LLM抽出値に委ねる）
type TaxableChoice = 'true' | 'false' | 'auto';

const taxableToChoice = (t: boolean | null): TaxableChoice =>
  t === null ? 'auto' : t ? 'true' : 'false';
const choiceToTaxable = (c: TaxableChoice): boolean | null =>
  c === 'auto' ? null : c === 'true';
const taxableLabel = (t: boolean | null): string =>
  t === null ? '自動判定' : t ? '課税' : '非課税';

interface EditState {
  postal_code: string;
  address: string;
  department: string;
  taxable: TaxableChoice;
}

const emptyNew = {
  canonical_name: '',
  postal_code: '',
  address: '',
  department: '',
  taxable: 'auto' as TaxableChoice,
};

export const CompanyMasterPanel: React.FC = () => {
  const [domain, setDomain] = useState<CompanyDomain>('sales');
  const [companies, setCompanies] = useState<CompanyMasterItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  // 新規追加フォーム
  const [newCompany, setNewCompany] = useState(emptyNew);
  const [creating, setCreating] = useState(false);

  // インライン編集
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const isPurchase = domain === 'purchase';

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCompanyMaster(domain, showInactive);
      setCompanies(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '一覧の読み込みに失敗しました');
    } finally {
      setLoading(false);
    }
  }, [domain, showInactive]);

  useEffect(() => {
    load();
  }, [load]);

  const extractError = (err: unknown): string => {
    // axios エラーの detail を拾う
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string };
    return anyErr?.response?.data?.detail || anyErr?.message || '処理に失敗しました';
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCompany.canonical_name.trim()) {
      setError('会社名を入力してください');
      return;
    }
    setCreating(true);
    setError(null);
    setSuccess(null);
    try {
      await createCompanyMaster({
        domain,
        canonical_name: newCompany.canonical_name.trim(),
        postal_code: newCompany.postal_code.trim(),
        address: newCompany.address.trim(),
        department: newCompany.department.trim(),
        taxable: isPurchase ? choiceToTaxable(newCompany.taxable) : null,
      });
      setSuccess(`「${newCompany.canonical_name.trim()}」を追加しました`);
      setNewCompany(emptyNew);
      await load();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setCreating(false);
    }
  };

  const startEdit = (c: CompanyMasterItem) => {
    setEditingId(c.id);
    setEditState({
      postal_code: c.postal_code,
      address: c.address,
      department: c.department,
      taxable: taxableToChoice(c.taxable),
    });
    setError(null);
    setSuccess(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditState(null);
  };

  const saveEdit = async (id: number) => {
    if (!editState) return;
    setSavingEdit(true);
    setError(null);
    try {
      await updateCompanyMaster(id, {
        postal_code: editState.postal_code,
        address: editState.address,
        department: editState.department,
        ...(isPurchase
          ? { taxable: choiceToTaxable(editState.taxable), set_taxable: true }
          : {}),
      });
      setSuccess('更新しました');
      cancelEdit();
      await load();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setSavingEdit(false);
    }
  };

  const handleToggleActive = async (c: CompanyMasterItem) => {
    setError(null);
    setSuccess(null);
    try {
      if (c.is_active) {
        if (!window.confirm(`「${c.canonical_name}」を無効化しますか？\n（過去の伝票は壊れません。今後のマッチング候補から外れます）`)) {
          return;
        }
        await deactivateCompanyMaster(c.id);
        setSuccess(`「${c.canonical_name}」を無効化しました`);
      } else {
        await updateCompanyMaster(c.id, { is_active: true });
        setSuccess(`「${c.canonical_name}」を再有効化しました`);
      }
      await load();
    } catch (err) {
      setError(extractError(err));
    }
  };

  const inputCls =
    'w-full px-2 py-1 border border-gray-300 rounded focus:ring-2 focus:ring-primary focus:border-transparent text-sm';

  return (
    <div>
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6">
        <p className="text-gray-700 leading-relaxed text-sm">
          納品書PDFから会社名を自動判定する際の<strong>マスタ（真値）</strong>です。
          ここに無い会社はアップロード時に「会社選択」に戻されます。
          <br />
          新しい得意先・仕入先はここで追加してください（即座に反映されます）。
        </p>
      </div>

      {/* 売上/仕入 切替 */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => { setDomain('sales'); cancelEdit(); }}
          className={`px-4 py-2 rounded-lg font-semibold text-sm transition-colors ${
            domain === 'sales' ? 'bg-primary text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          得意先（売上）
        </button>
        <button
          onClick={() => { setDomain('purchase'); cancelEdit(); }}
          className={`px-4 py-2 rounded-lg font-semibold text-sm transition-colors ${
            domain === 'purchase' ? 'bg-primary text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          仕入先（仕入）
        </button>
      </div>

      {error && <Message type="error" className="mb-4">{error}</Message>}
      {success && <Message type="success" className="mb-4">{success}</Message>}

      {/* 新規追加フォーム */}
      <form onSubmit={handleCreate} className="bg-white rounded-lg shadow p-4 mb-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-3">
          ＋ 新規{isPurchase ? '仕入先' : '得意先'}を追加
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">会社名（必須）</label>
            <input
              type="text"
              value={newCompany.canonical_name}
              onChange={(e) => setNewCompany({ ...newCompany, canonical_name: e.target.value })}
              className={inputCls}
              placeholder="例: （株）サンプル商事"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">郵便番号</label>
            <input
              type="text"
              value={newCompany.postal_code}
              onChange={(e) => setNewCompany({ ...newCompany, postal_code: e.target.value })}
              className={inputCls}
              placeholder="例: 150-0002"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">事業部</label>
            <input
              type="text"
              value={newCompany.department}
              onChange={(e) => setNewCompany({ ...newCompany, department: e.target.value })}
              className={inputCls}
              placeholder="例: 営業部"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">住所（ビル名含む）</label>
            <input
              type="text"
              value={newCompany.address}
              onChange={(e) => setNewCompany({ ...newCompany, address: e.target.value })}
              className={inputCls}
              placeholder="例: 東京都渋谷区渋谷1丁目20-1 井門美竹ビル2"
            />
          </div>
          {isPurchase && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">課税区分</label>
              <select
                value={newCompany.taxable}
                onChange={(e) => setNewCompany({ ...newCompany, taxable: e.target.value as TaxableChoice })}
                className={inputCls}
              >
                <option value="auto">自動判定（LLM抽出値）</option>
                <option value="true">課税</option>
                <option value="false">非課税</option>
              </select>
            </div>
          )}
        </div>
        <div className="mt-4">
          <Button type="submit" variant="primary" loading={creating}>
            追加
          </Button>
        </div>
      </form>

      {/* 一覧 */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-lg font-semibold text-gray-700">
          登録済み一覧（{companies.length}件）
        </h3>
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          無効化済みも表示
        </label>
      </div>

      {loading ? (
        <Spinner message="読み込み中..." />
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">会社名</th>
                <th className="px-3 py-2 font-medium">郵便番号</th>
                <th className="px-3 py-2 font-medium">住所</th>
                <th className="px-3 py-2 font-medium">事業部</th>
                {isPurchase && <th className="px-3 py-2 font-medium">課税</th>}
                <th className="px-3 py-2 font-medium w-40">操作</th>
              </tr>
            </thead>
            <tbody>
              {companies.length === 0 && (
                <tr>
                  <td colSpan={isPurchase ? 6 : 5} className="px-3 py-6 text-center text-gray-400">
                    登録がありません
                  </td>
                </tr>
              )}
              {companies.map((c) => {
                const editing = editingId === c.id;
                return (
                  <tr
                    key={c.id}
                    className={`border-t border-gray-100 ${!c.is_active ? 'bg-gray-50 text-gray-400' : ''}`}
                  >
                    <td className="px-3 py-2">
                      {c.canonical_name}
                      {!c.is_active && <span className="ml-2 text-xs">(無効)</span>}
                    </td>
                    {editing && editState ? (
                      <>
                        <td className="px-3 py-2">
                          <input
                            className={inputCls}
                            value={editState.postal_code}
                            onChange={(e) => setEditState({ ...editState, postal_code: e.target.value })}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <input
                            className={inputCls}
                            value={editState.address}
                            onChange={(e) => setEditState({ ...editState, address: e.target.value })}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <input
                            className={inputCls}
                            value={editState.department}
                            onChange={(e) => setEditState({ ...editState, department: e.target.value })}
                          />
                        </td>
                        {isPurchase && (
                          <td className="px-3 py-2">
                            <select
                              className={inputCls}
                              value={editState.taxable}
                              onChange={(e) => setEditState({ ...editState, taxable: e.target.value as TaxableChoice })}
                            >
                              <option value="auto">自動判定</option>
                              <option value="true">課税</option>
                              <option value="false">非課税</option>
                            </select>
                          </td>
                        )}
                        <td className="px-3 py-2">
                          <div className="flex gap-2">
                            <button
                              onClick={() => saveEdit(c.id)}
                              disabled={savingEdit}
                              className="text-primary font-semibold hover:underline disabled:opacity-50"
                            >
                              保存
                            </button>
                            <button
                              onClick={cancelEdit}
                              className="text-gray-500 hover:underline"
                            >
                              取消
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2">{c.postal_code || '—'}</td>
                        <td className="px-3 py-2">{c.address || '—'}</td>
                        <td className="px-3 py-2">{c.department || '—'}</td>
                        {isPurchase && <td className="px-3 py-2">{taxableLabel(c.taxable)}</td>}
                        <td className="px-3 py-2">
                          <div className="flex gap-3">
                            <button
                              onClick={() => startEdit(c)}
                              className="text-primary hover:underline"
                            >
                              編集
                            </button>
                            <button
                              onClick={() => handleToggleActive(c)}
                              className={c.is_active ? 'text-red-500 hover:underline' : 'text-green-600 hover:underline'}
                            >
                              {c.is_active ? '無効化' : '再有効化'}
                            </button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
