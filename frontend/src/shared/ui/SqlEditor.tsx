import { autocompletion, closeBrackets } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { MySQL, PostgreSQL, sql, SQLDialect, StandardSQL } from "@codemirror/lang-sql";
import { bracketMatching, HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Compartment, EditorState } from "@codemirror/state";
import {
  drawSelection,
  EditorView,
  highlightActiveLine,
  keymap,
  lineNumbers,
  placeholder as ph,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";
import s from "./SqlEditor.module.css";

export type SqlSchema = Record<string, string[]>;

const DIALECTS: Record<string, SQLDialect> = { postgres: PostgreSQL, mysql: MySQL };

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--brand)", fontWeight: "700" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--pos-text)" },
  { tag: tags.number, color: "var(--accent-ems)" },
  { tag: tags.comment, color: "var(--ink-4)", fontStyle: "italic" },
  { tag: [tags.function(tags.variableName), tags.standard(tags.name)], color: "var(--accent-ab)" },
  { tag: tags.typeName, color: "var(--accent-kb)" },
]);

const theme = EditorView.theme({
  "&": { color: "var(--ink)", backgroundColor: "var(--field-bg)", fontSize: "13.5px", height: "100%" },
  ".cm-content": { fontFamily: "var(--font-mono)", caretColor: "var(--brand)" },
  ".cm-gutters": { backgroundColor: "var(--surface-2)", color: "var(--ink-4)", border: "none" },
  ".cm-activeLine": { backgroundColor: "var(--row-hover)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--row-hover)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": { backgroundColor: "var(--row-selected)" },
  ".cm-tooltip": { backgroundColor: "var(--surface)", border: "1px solid var(--line)", borderRadius: "6px" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "var(--brand)", color: "#fff" },
  ".cm-scroller": { overflow: "auto" },
});

/** SQL editor with schema-aware autocompletion (tables and columns from the catalog). */
export function SqlEditor({
  value,
  onChange,
  onRun,
  schema,
  dialect,
  placeholder,
  minHeight = 220,
  readOnly,
}: {
  value: string;
  onChange?: (v: string) => void;
  onRun?: () => void;
  schema?: SqlSchema;
  dialect?: string;
  placeholder?: string;
  minHeight?: number;
  readOnly?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const langConf = useRef(new Compartment());
  const cb = useRef({ onChange, onRun });
  cb.current = { onChange, onRun };

  useEffect(() => {
    if (!host.current) return;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          drawSelection(),
          highlightActiveLine(),
          bracketMatching(),
          closeBrackets(),
          autocompletion({ activateOnTyping: true }),
          syntaxHighlighting(highlight),
          theme,
          EditorState.readOnly.of(!!readOnly),
          langConf.current.of(sql({ dialect: StandardSQL })),
          ph(placeholder ?? ""),
          keymap.of([
            { key: "Mod-Enter", run: () => (cb.current.onRun?.(), true) },
            indentWithTab,
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) cb.current.onChange?.(u.state.doc.toString());
          }),
          EditorView.lineWrapping,
        ],
      }),
    });
    view.current = v;
    return () => v.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    view.current?.dispatch({
      effects: langConf.current.reconfigure(
        sql({ dialect: DIALECTS[dialect ?? ""] ?? StandardSQL, schema, upperCaseKeywords: true }),
      ),
    });
  }, [schema, dialect]);

  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} className={s.editor} style={{ minHeight }} />;
}
