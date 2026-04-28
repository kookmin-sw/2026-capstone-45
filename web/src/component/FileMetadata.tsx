interface FileMetadataProps {
	filename: string;
	uploadedAt: Date;
	sizeBytes: number;
}

export const FileMetadata = ({
	filename,
	uploadedAt,
	sizeBytes,
}: FileMetadataProps) => {
	const formatSize = (bytes: number) => {
		if (bytes < 1024 * 1024) {
			return `${(bytes / 1024).toFixed(1)} KB`;
		}
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	};

	const formattedDate = uploadedAt.toLocaleDateString(undefined, {
		dateStyle: "short",
	});

	return (
		<div className="flex flex-col gap-0.5 text-sm">
			<div className="font-medium text-foreground truncate">{filename}</div>
			<div className="text-muted-foreground flex gap-2">
				<span>{formattedDate}</span>
				<span>•</span>
				<span>{formatSize(sizeBytes)}</span>
			</div>
		</div>
	);
};
