import { Database, FileSpreadsheet, HardDrive, Sheet } from "lucide-react";

export function typeIcon(type: string) {
  if (type === "files") return <FileSpreadsheet size={20} />;
  if (type === "gsheets") return <Sheet size={20} />;
  if (type === "s3") return <HardDrive size={20} />;
  return <Database size={20} />;
}
