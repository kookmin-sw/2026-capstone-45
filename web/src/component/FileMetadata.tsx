import { filesize } from 'filesize';

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
  const formattedSize = filesize(sizeBytes);
  const formattedDate = uploadedAt.toLocaleDateString(undefined, {
    dateStyle: 'short',
  });

  return (
    <div>
      <div>{filename}</div>
      <div>{formattedDate}</div>
      <div>{formattedSize}</div>
    </div>
  );
};
