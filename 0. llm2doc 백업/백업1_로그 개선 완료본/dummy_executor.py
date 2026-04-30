import concurrent.futures


class DummyExecutor(concurrent.futures.Executor):
    """
    A dummy executor that executes tasks synchronously in the current thread.
    Useful for testing or debugging concurrent code sequentially.
    """

    def submit(self, fn, *args, **kwargs):
        """
        Executes the callable immediately and returns a completed Future.
        """
        future = concurrent.futures.Future()
        try:
            # Execute the function right away
            result = fn(*args, **kwargs)
            future.set_result(result)
        except BaseException as exc:
            # Catch exceptions to mimic standard Executor behavior
            future.set_exception(exc)

        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        """
        No-op since there are no worker threads or processes to clean up.
        """
        pass
