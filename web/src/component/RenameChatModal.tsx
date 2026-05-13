import { Button, Group, Modal, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { useMutationRenameChat } from "#root/query/renameChat";

interface RenameChatModalProps {
	chatId: string;
	currentName: string;
	visible: boolean;
	onClose: () => void;
}

export const RenameChatModal = ({
	chatId,
	currentName,
	visible,
	onClose,
}: RenameChatModalProps) => {
	const [renameValue, setRenameValue] = useState(currentName);
	const renameChatMutation = useMutationRenameChat();

	useEffect(() => {
		if (visible) {
			setRenameValue(currentName);
		}
	}, [visible, currentName]);

	const handleConfirm = () => {
		if (!renameValue.trim()) return;

		renameChatMutation.mutateAsync({
			chatId,
			displayName: renameValue.trim(),
		});

		onClose();
		setRenameValue("");
	};

	return (
		<Modal opened={visible} title="채팅 이름 바꾸기" onClose={onClose} centered>
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
