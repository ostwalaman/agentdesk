import { useEffect, useRef, useState } from "react";
import { AlertTriangle, BarChart3, RefreshCw, Upload, DatabaseZap } from "lucide-react";
import ChatWindow from "./components/ChatWindow";

type PipelineStage = {
  stage: string;
  count: number;
  total_value: number;
  average_probability: number;
  forecasted_revenue: number;
};

type PipelineSummary = {
  stages: PipelineStage[];
  total_pipeline: number;
  total_forecasted_revenue: number;
};

type AtRiskDeal = {
  opportunity_id: number;
  opportunity: string;
  account: string;
  amount: number;
  probability: number;
  days_left: number;
};

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0
});

function Sidebar() {
  const [pipeline, setPipeline] = useState<PipelineSummary | null>(null);
  const [deals, setDeals] = useState<AtRiskDeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionStatus, setActionStatus] = useState<string>("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh() {
    try {
      const [pipelineResponse, dealsResponse] = await Promise.all([
        fetch("/api/pipeline"),
        fetch("/api/deals/at-risk")
      ]);
      if (pipelineResponse.ok) {
        setPipeline(await pipelineResponse.json());
      }
      if (dealsResponse.ok) {
        setDeals(await dealsResponse.json());
      }
    } finally {
      setLoading(false);
    }
  }

  async function syncSalesforce() {
    setIsSyncing(true);
    setActionStatus("Syncing Salesforce...");
    try {
      const response = await fetch("/api/sync/salesforce", { method: "POST" });
      if (!response.ok) {
        throw new Error(`Sync failed with status ${response.status}`);
      }
      const result: { accounts: number; contacts: number; opportunities: number; tasks: number } = await response.json();
      setActionStatus(
        `Synced ${result.accounts} accounts, ${result.contacts} contacts, ${result.opportunities} opportunities, ${result.tasks} tasks.`
      );
      await refresh();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Salesforce sync failed.");
    } finally {
      setIsSyncing(false);
    }
  }

  async function importCsv(files: File[]) {
    if (files.length === 0) {
      setActionStatus("Choose one or more CSV files first.");
      return;
    }
    setIsImporting(true);
    const fileNames = files.map((file) => file.name);
    setSelectedFiles(fileNames);
    setUploadProgress(0);
    setActionStatus(`Uploading ${fileNames.length} file${fileNames.length === 1 ? "" : "s"}...`);
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file, file.name));
      const result: {
        filenames?: string[];
        mode?: string;
        rows_processed: number;
        files_processed?: number;
        accounts: number;
        contacts: number;
        opportunities: number;
        tasks: number;
      } = await uploadCsvFiles(formData, (progress) => setUploadProgress(progress));
      setUploadProgress(100);
      setActionStatus(
        `Imported ${result.files_processed ?? fileNames.length} file${(result.files_processed ?? fileNames.length) === 1 ? "" : "s"}, ${result.rows_processed} rows${result.mode ? ` (${result.mode})` : ""}: ${result.accounts} accounts, ${result.contacts} contacts, ${result.opportunities} opportunities, ${result.tasks} tasks.`
      );
      await refresh();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "CSV import failed.");
    } finally {
      setIsImporting(false);
    }
  }

  function onChooseFiles(files: FileList | null) {
    const nextFiles = files ? Array.from(files).filter((file) => file.name.toLowerCase().endsWith(".csv")) : [];
    setPendingFiles(nextFiles);
    setSelectedFiles(nextFiles.map((file) => file.name));
    setUploadProgress(0);
    if (nextFiles.length > 0) {
      setActionStatus(`${nextFiles.length} CSV file${nextFiles.length === 1 ? "" : "s"} ready to upload.`);
    } else {
      setActionStatus("No CSV files selected.");
    }
  }

  function uploadCsvFiles(
    formData: FormData,
    onProgress: (progress: number) => void
  ): Promise<{
    filenames?: string[];
    mode?: string;
    rows_processed: number;
    files_processed?: number;
    accounts: number;
    contacts: number;
    opportunities: number;
    tasks: number;
  }> {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", "/api/import/csv");
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) {
          resolve(JSON.parse(request.responseText));
        } else {
          reject(new Error(`Import failed with status ${request.status}`));
        }
      };
      request.onerror = () => reject(new Error("CSV upload failed."));
      request.send(formData);
    });
  }

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 60000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <aside className="flex h-full w-full flex-col gap-5 overflow-y-auto bg-navy-950 p-5 text-white lg:w-[360px]">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-electric-300">CRM Command Center</p>
          <h2 className="mt-2 text-xl font-semibold">AgentDesk</h2>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-electric-300 transition hover:bg-white/10"
          title="Refresh"
          aria-label="Refresh dashboard"
        >
          <RefreshCw size={17} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <section className="rounded-lg border border-white/10 bg-white/[0.06] p-4">
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => void syncSalesforce()}
            disabled={isSyncing || isImporting}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-electric-500 px-3 py-2 text-xs font-semibold text-white transition hover:bg-electric-400 disabled:cursor-not-allowed disabled:bg-slate-600"
          >
            <DatabaseZap size={15} />
            {isSyncing ? "Syncing" : "Sync Salesforce"}
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isSyncing || isImporting}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/10 px-3 py-2 text-xs font-semibold text-white transition hover:bg-white/15 disabled:cursor-not-allowed disabled:bg-slate-600"
          >
            <Upload size={15} />
            Choose CSV files
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          multiple
          className="hidden"
          disabled={isSyncing || isImporting}
          onChange={(event) => {
            onChooseFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => void importCsv(pendingFiles)}
          disabled={isSyncing || isImporting || pendingFiles.length === 0}
          className="mt-2 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-navy-950 transition hover:bg-electric-300 disabled:cursor-not-allowed disabled:bg-slate-500 disabled:text-slate-300"
        >
          <Upload size={15} />
          {isImporting ? "Uploading" : `Upload selected${pendingFiles.length ? ` (${pendingFiles.length})` : ""}`}
        </button>
        {(selectedFiles.length > 0 || actionStatus) && (
          <div className="mt-3 space-y-2">
            {selectedFiles.length > 0 && (
              <div className="rounded-lg bg-navy-900/70 p-2">
                <div className="flex items-center justify-between gap-3 text-xs font-semibold text-slate-200">
                  <span>Selected files</span>
                  <span>{selectedFiles.length}</span>
                </div>
                <p className="mt-1 truncate text-xs text-slate-400" title={selectedFiles.join(", ")}>
                  {selectedFiles.join(", ")}
                </p>
              </div>
            )}
            {(isImporting || uploadProgress > 0) && (
              <div>
                <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
                  <span>Upload progress</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-electric-500 transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}
            {actionStatus && <p className="text-xs leading-5 text-slate-300">{actionStatus}</p>}
          </div>
        )}
      </section>

      <section className="rounded-lg border border-white/10 bg-white/[0.06] p-4">
        <div className="mb-4 flex items-center gap-2">
          <BarChart3 size={18} className="text-electric-300" />
          <h3 className="text-sm font-semibold">Pipeline Overview</h3>
        </div>
        <div className="space-y-3">
          {pipeline?.stages.map((stage) => (
            <div key={stage.stage}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-medium text-slate-200">{stage.stage}</span>
                <span className="text-slate-400">{stage.count} deals</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-electric-500"
                  style={{
                    width: `${pipeline.total_pipeline ? Math.max((stage.total_value / pipeline.total_pipeline) * 100, 4) : 0}%`
                  }}
                />
              </div>
            </div>
          ))}
          {!pipeline && <p className="text-sm text-slate-400">Waiting for backend data...</p>}
        </div>
        {pipeline && (
          <div className="mt-5 grid grid-cols-2 gap-3 border-t border-white/10 pt-4">
            <div>
              <p className="text-xs text-slate-400">Pipeline</p>
              <p className="mt-1 text-lg font-semibold">{currency.format(pipeline.total_pipeline)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Forecast</p>
              <p className="mt-1 text-lg font-semibold">{currency.format(pipeline.total_forecasted_revenue)}</p>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-white/10 bg-white/[0.06] p-4">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle size={18} className="text-amber-300" />
          <h3 className="text-sm font-semibold">At-Risk Deals</h3>
        </div>
        <div className="space-y-3">
          {deals.slice(0, 3).map((deal) => (
            <div key={deal.opportunity_id} className="rounded-lg border border-white/10 bg-navy-900/70 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-white">{deal.account}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-400">{deal.opportunity}</p>
                </div>
                <span className="rounded-full bg-amber-300/15 px-2 py-1 text-xs font-semibold text-amber-200">
                  {deal.days_left}d
                </span>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-slate-300">
                <span>{currency.format(deal.amount)}</span>
                <span>{deal.probability}% probability</span>
              </div>
            </div>
          ))}
          {deals.length === 0 && <p className="text-sm text-slate-400">No at-risk deals found.</p>}
        </div>
      </section>
    </aside>
  );
}

export default function App() {
  return (
    <main className="flex h-full flex-col bg-navy-950 lg:flex-row">
      <Sidebar />
      <ChatWindow />
    </main>
  );
}
