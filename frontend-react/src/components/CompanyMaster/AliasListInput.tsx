import React, { useState } from 'react';

interface Props {
  aliases: string[];
  onChange: (next: string[]) => void;
  inputCls: string;
  /** 一覧のインライン編集ではラベルを省く */
  compact?: boolean;
  disabled?: boolean;
}

/**
 * 「伝票上の別名」の入力（チップ表示 + 追加欄）
 * 例: gf.A㈱ に「CLANE DESIGN CO.,LTD」「CLANE」を登録すると、
 *     伝票がその表記で読まれても gf.A㈱ に集計される
 */
export const AliasListInput: React.FC<Props> = ({
  aliases,
  onChange,
  inputCls,
  compact = false,
  disabled = false,
}) => {
  const [draft, setDraft] = useState('');

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (aliases.some((a) => a.trim().toLowerCase() === v.toLowerCase())) {
      setDraft('');
      return;
    }
    onChange([...aliases, v]);
    setDraft('');
  };

  const remove = (idx: number) => {
    onChange(aliases.filter((_, i) => i !== idx));
  };

  return (
    <div>
      {!compact && (
        <label className="block text-xs font-medium text-gray-600 mb-1">
          伝票上の別名（この表記で伝票に書かれていたらこの会社に集計）
        </label>
      )}
      {aliases.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1">
          {aliases.map((a, i) => (
            <span
              key={`${a}-${i}`}
              className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 text-blue-800 rounded px-2 py-0.5 text-xs"
            >
              {a}
              {!disabled && (
                <button
                  type="button"
                  onClick={() => remove(i)}
                  className="text-blue-400 hover:text-red-600"
                  title="この別名を削除"
                  aria-label={`別名 ${a} を削除`}
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      {!disabled && (
        <div className="flex gap-1">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                add();
              }
            }}
            placeholder={compact ? '別名を追加' : '例: CLANE DESIGN CO.,LTD'}
            className={inputCls}
          />
          <button
            type="button"
            onClick={add}
            className="shrink-0 px-3 py-1 text-sm rounded border border-gray-300 bg-white hover:bg-gray-50 text-gray-700"
          >
            追加
          </button>
        </div>
      )}
    </div>
  );
};
