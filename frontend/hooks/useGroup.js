// The rows of the group form. Two empty rows to start with.
import { useCallback, useRef, useState } from "react";
import { MAX_TRAVELLERS } from "../services/constants.js";
import { readGroup } from "../services/tripText.js";

const emptyRow = (id) => ({ id, name: "", likes: "", avoid: "" });

export function useGroup() {
  const [rows, setRows] = useState([emptyRow(1), emptyRow(2)]);
  const nextId = useRef(3);

  const add = () => setRows((all) => (all.length >= MAX_TRAVELLERS ? all : [...all, emptyRow(nextId.current++)]));
  const remove = (id) => setRows((all) => all.filter((r) => r.id !== id));
  const change = (id, key, value) => setRows((all) => all.map((r) => (r.id === id ? { ...r, [key]: value } : r)));
  const read = useCallback(() => readGroup(rows), [rows]);

  return { rows, add, remove, change, read };
}
