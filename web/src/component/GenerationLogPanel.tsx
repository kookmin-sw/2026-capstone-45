import { Button } from "@mantine/core";
import { Clock3, FileJson, Loader2, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChatMessageEntry } from "#root/query/chatDetail";
import { useQueryChatLogFile, useQueryChatLogs } from "#root/query/chatLogs";
import { cn } from "#root/utils/cn";
import { FoldableMessage } from "./FoldableMessage";
import { MessageList } from "./MessageList";

interface GenerationLogPanelProps {
	chatId: number;
	messages: ChatMessageEntry[];
}

const statusLabel: Record<string, string> = {
	not_started: "대기 중",
	created: "준비됨",
	running: "실행 중",
	completed: "완료",
	failed: "실패",
};

const statusClassName: Record<string, string> = {
	not_started: "bg-slate-100 text-slate-700",
	created: "bg-slate-100 text-slate-700",
	running: "bg-blue-50 text-blue-700",
	completed: "bg-emerald-50 text-emerald-700",
	failed: "bg-red-50 text-red-700",
};

const formatDuration = (durationMs: number | null | undefined) => {
	if (durationMs == null) return "";
	if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
	return `${(durationMs / 1000).toFixed(1)}s`;
};

const stringify = (value: unknown) => {
	if (value == null) return "";
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value, null, 2);
	} catch (_error) {
		return String(value);
	}
};

const summaryText = (summary: Record<string, unknown>, key: string) => {
	const value = summary[key];
	if (value == null) return "-";
	if (typeof value === "string" || typeof value === "number") return String(value);
	return stringify(value);
};

const targetDocumentLabel = (summary: Record<string, unknown>) => {
	const docId = summary.target_doc_id;
	const displayName = summary.target_display_name;
	if (docId != null || displayName != null) {
		return [docId != null ? `doc_id=${docId}` : null, displayName]
			.filter(Boolean)
			.join(" / ");
	}
	return summaryText(summary, "target_doc");
};

export const GenerationLogPanel = ({
	chatId,
	messages,
}: GenerationLogPanelProps) => {
	const [selectedPath, setSelectedPath] = useState<string | null>(null);
	const { data, isFetching } = useQueryChatLogs(chatId, Number.isFinite(chatId));
	const { data: selectedFileContent } = useQueryChatLogFile(
		chatId,
		selectedPath,
		selectedPath !== null,
	);

	const userMessage = useMemo(
		() => messages.find((message) => message.depth === 10)?.content,
		[messages],
	);
	const events = data?.events ?? [];
	const latestEvent = data?.latest_event;
	const files = data?.files ?? { llm: [], search: [], retrieval: [], output: [] };
	const fileGroups = [
		["LLM", files.llm],
		["Search", files.search],
		["Retrieval", files.retrieval],
		["Output", files.output],
	] as const;

	return (
		<div className="flex flex-col w-full gap-4 pb-4">
			{userMessage && (
				<div className="flex justify-end">
					<div className="max-w-[80%] px-4 py-2 rounded-2xl rounded-tr-none bg-primary text-primary-foreground whitespace-pre-wrap break-words">
						{userMessage}
					</div>
				</div>
			)}

			<section className="border border-border rounded-lg p-4 bg-background">
				<div className="flex items-center justify-between gap-3 mb-3">
					<div>
						<h3 className="font-semibold text-sm">생성 상태</h3>
						<p className="text-xs text-muted-foreground">
							chat_id={chatId}
						</p>
					</div>
					<div className="flex items-center gap-2">
						{isFetching && <RefreshCw className="w-4 h-4 animate-spin text-muted-foreground" />}
						<span
							className={cn(
								"px-2 py-1 rounded text-xs font-semibold",
								statusClassName[data?.status ?? "not_started"],
							)}
						>
							{statusLabel[data?.status ?? "not_started"] ?? data?.status}
						</span>
					</div>
				</div>

				<div className="grid grid-cols-2 gap-2 text-xs">
					<div className="text-muted-foreground">대상 문서</div>
					<div className="font-mono break-words">
						{targetDocumentLabel(data?.summary ?? {})}
					</div>
					<div className="text-muted-foreground">전체 시간</div>
					<div className="font-mono">
						{formatDuration(
							(data?.summary?.total_duration_ms as number | undefined) ?? null,
						) || "-"}
					</div>
					<div className="text-muted-foreground">마지막 이벤트</div>
					<div className="font-mono break-words">
						{latestEvent
							? `${latestEvent.component} / ${latestEvent.event}`
							: "-"}
					</div>
				</div>
			</section>

			<section className="border border-border rounded-lg p-4 bg-background">
				<div className="flex items-center gap-2 mb-3">
					<Clock3 className="w-4 h-4 text-muted-foreground" />
					<h3 className="font-semibold text-sm">단계별 타임라인</h3>
				</div>
				{events.length === 0 ? (
					<div className="flex items-center gap-2 text-sm text-muted-foreground">
						<Loader2 className="w-4 h-4" />
						아직 기록된 이벤트가 없습니다.
					</div>
				) : (
					<div className="space-y-2 max-h-72 overflow-y-auto pr-1">
						{events.slice(-120).map((event, index) => (
							<div
								// biome-ignore lint/suspicious/noArrayIndexKey: append-only event log
								key={`${event.ts ?? index}-${event.event}`}
								className="grid grid-cols-[1fr_auto] gap-3 border-l-2 border-border pl-3 py-1"
							>
								<div className="min-w-0">
									<div className="text-sm font-mono break-words">
										{event.component} / {event.event}
									</div>
									{event.time && (
										<div className="text-xs text-muted-foreground">
											{event.time}
										</div>
									)}
								</div>
								<div className="text-xs font-mono text-muted-foreground whitespace-nowrap">
									{formatDuration(event.duration_ms)}
								</div>
							</div>
						))}
					</div>
				)}
			</section>

			<section className="border border-border rounded-lg p-4 bg-background">
				<div className="flex items-center gap-2 mb-3">
					<FileJson className="w-4 h-4 text-muted-foreground" />
					<h3 className="font-semibold text-sm">구조화 로그 파일</h3>
				</div>
				<div className="grid grid-cols-2 gap-3">
					{fileGroups.map(([label, paths]) => (
						<div key={label} className="min-w-0">
							<div className="text-xs font-semibold text-muted-foreground mb-1">
								{label}
							</div>
							<div className="space-y-1">
								{paths.length === 0 ? (
									<div className="text-xs text-muted-foreground">파일 없음</div>
								) : (
									paths.map((path) => (
										<Button
											key={path}
											variant={selectedPath === path ? "light" : "subtle"}
											color="gray"
											size="compact-sm"
											fullWidth
											justify="flex-start"
											onClick={() => setSelectedPath(path)}
										>
											<span className="truncate font-mono text-xs">{path}</span>
										</Button>
									))
								)}
							</div>
						</div>
					))}
				</div>

				{selectedPath && (
					<div className="mt-4">
						<div className="text-xs font-semibold text-muted-foreground mb-1">
							{selectedPath}
						</div>
						<pre className="max-h-80 overflow-auto rounded bg-muted/40 p-3 text-xs font-mono whitespace-pre-wrap break-words">
							{selectedFileContent ?? "loading..."}
						</pre>
					</div>
				)}
			</section>

			<FoldableMessage title="기존 메시지 로그" defaultOpen={false}>
				<MessageList messages={messages} />
			</FoldableMessage>
		</div>
	);
};
