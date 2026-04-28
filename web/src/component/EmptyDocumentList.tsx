import { FilePlus } from "lucide-react";

interface EmptyDocumentListProps {
	onAddFile: () => void;
}

export const EmptyDocumentList = ({ onAddFile }: EmptyDocumentListProps) => {
	return (
		<div className="flex flex-col items-center justify-center flex-1 w-full h-full min-h-100 gap-4">
			<div className="p-6 rounded-full bg-muted">
				<FilePlus className="w-12 h-12 text-muted-foreground opacity-50" />
			</div>
			<div className="text-center">
				<h3 className="text-lg font-semibold text-foreground">
					업로드된 문서가 없습니다
				</h3>
				<p className="text-sm text-muted-foreground mt-1">
					지원되는 형식의 문서를 업로드한 후 시작해보세요
				</p>
			</div>
			<button
				type="button"
				onClick={onAddFile}
				className="mt-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-lg font-semibold shadow-sm hover:opacity-90 transition-all active:scale-95"
			>
				파일 추가
			</button>
		</div>
	);
};
