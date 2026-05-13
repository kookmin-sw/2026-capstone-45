import { Button, Group, Modal, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { useMutationRenameDocument } from "#root/query/renameDocument";

interface RenameDocumentModalProps {
	docId: number;
	currentName: string;
	visible: boolean;
	onClose: () => void;
}

export const RenameDocumentModal = ({
	docId,
	currentName,
	visible,
	onClose,
}: RenameDocumentModalProps) => {
	const [renameValue, setRenameValue] = useState(currentName);
	const { mutateAsync: renameDocument } = useMutationRenameDocument();

	useEffect(() => {
		if (visible) {
			setRenameValue(currentName);
		}
	}, [visible, currentName]);

	const handleConfirm = () => {
		if (!renameValue.trim()) return;

		renameDocument({
			docId,
			displayName: renameValue.trim(),
		});

		onClose();
		setRenameValue("");
	};

	return (
		<Modal opened={visible} title="문서 이름 바꾸기" onClose={onClose} centered>
			<TextInput
				label="새 이름"
				value={renameValue}
				onChange={(e) => setRenameValue(e.target.value)}
				onKeyDown={(e) => {
					if (e.key === "Enter") {
						handleConfirm();
					}
				}}
				autoFocus
				maxLength={64}
			/>
			<Group justify="flex-end" mt="xl">
				<Button variant="subtle" color="gray" onClick={onClose}>
					취소
				</Button>
				<Button
					onClick={handleConfirm}
					disabled={!renameValue.trim() || renameValue.trim() === currentName}
				>
					저장
				</Button>
			</Group>
		</Modal>
	);
};
