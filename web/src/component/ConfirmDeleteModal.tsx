import { Button, Group, Modal, Text } from "@mantine/core";

interface ConfirmDeleteModalProps {
	visible: boolean;
	title: string;
	message: string;
	onCancel: () => void;
	onConfirm: () => void;
}

export const ConfirmDeleteModal = ({
	visible,
	title,
	message,
	onCancel,
	onConfirm,
}: ConfirmDeleteModalProps) => {
	return (
		<Modal opened={visible} onClose={onCancel} title={title} centered>
			<Text size="sm">{message}</Text>
			<Group justify="flex-end" mt="xl">
				<Button variant="subtle" color="gray" onClick={onCancel}>
					취소
				</Button>
				<Button color="red" onClick={onConfirm}>
					삭제
				</Button>
			</Group>
		</Modal>
	);
};
