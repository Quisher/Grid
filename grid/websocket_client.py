import binascii
from typing import List
from typing import Union

import torch

import syft as sy
from syft import messaging
from syft.generic.tensor import AbstractTensor
from syft.workers import BaseWorker
from syft.federated import FederatedClient
from syft.codes import MSGTYPE

from grid.client import GridClient


class WebsocketGridClient(GridClient, FederatedClient):
    """Websocket Grid Client."""

    def __init__(
        self,
        hook,
        addr: str,
        id: Union[int, str] = 0,
        log_msgs: bool = False,
        verbose: bool = False,
        data: List[Union[torch.Tensor, AbstractTensor]] = None,
    ):
        """
        Args:
            hook : a normal TorchHook object
            addr : the address this client connects to
            id : the unique id of the worker (string or int)
            log_msgs : whether or not all messages should be
                saved locally for later inspection.
            verbose : a verbose option - will print all messages
                sent/received to stdout
            data : any initial tensors the server should be
                initialized with (such as datasets)
        """

        # Unfortunately, socketio will throw an exception on import if it's in a
        # thread. This occurs when Flask is in development mode
        import socketio

        self.uri = addr
        self.response_from_client = None
        self.wait_for_client_event = False

        # Creates the connection with the server
        self.__sio = socketio.Client()
        super().__init__(
            addr=addr, hook=hook, id=id, data=data, log_msgs=log_msgs, verbose=verbose
        )

        @self.__sio.on("/identity/")
        def check_identity(msg):
            if msg != "OpenGrid":
                raise PermissionError("App is not an OpenGrid app")

        @self.__sio.on("/cmd-response")
        def on_client_result(args):
            if log_msgs:
                print("Receiving result from client {}".format(args))
            try:
                # The server broadcasted the results from another client
                self.response_from_client = binascii.unhexlify(args[2:-1])
            except:
                raise Exception(args)

            # Tell the wait_for_client_event to clear up and continue execution
            self.wait_for_client_event = False

        @self.__sio.on("/connect-node-response")
        def connect_node(msg):
            if self.verbose:
                print("Connect Grid Node: ", msg)

    def _send_msg(self, message: bin) -> bin:
        raise NotImplementedError

    def _recv_msg(self, message: bin) -> bin:
        if self.__sio.eio.state != "connected":
            raise ConnectionError("Worker is not connected to the server")

        message = str(binascii.hexlify(message))
        # Sends the message to the server
        self.__sio.emit("/cmd", {"message": message})

        self.wait_for_client_event = True
        # Wait until the server gets back with a result or an ACK
        while self.wait_for_client_event:
            self.__sio.sleep()

        # Return the result
        if self.response_from_client == "ACK":
            # Empty result for the serialiser to continue
            return sy.serde.serialize(b"")
        return self.response_from_client

    def connect_grid_node(self, worker, sleep_time=0.5):
        self.__sio.emit("/connect-node", {"uri": worker.uri, "id": worker.id})
        self.__sio.sleep(sleep_time)

    def search(self, *query):
        # Prepare a message requesting the websocket server to search among its objects
        message = sy.Message(MSGTYPE.SEARCH, query)
        serialized_message = sy.serde.serialize(message)

        # Send the message and return the deserialized response.
        response = self._recv_msg(serialized_message)
        return sy.serde.deserialize(response)

    def get_ptr(self, obj_id):
        message = messaging.PlanCommandMessage((obj_id,), "get_ptr")
        serialized_message = sy.serde.serialize(message)
        response = self._recv_msg(serialized_message)
        return sy.serde.deserialize(response)

    def fetch_plan(self, plan_id):
        message = messaging.PlanCommandMessage((plan_id,), "fetch_plan")
        serialized_message = sy.serde.serialize(message)
        # Send the message and return the deserialized response.
        response = self._recv_msg(serialized_message)
        plan = sy.serde.deserialize(response)

        if plan.state_ids:
            state_ids = []
            for state_id in plan.state_ids:
                ptr = self.get_ptr(state_id)
                ptr.owner = sy.hook.local_worker
                sy.hook.local_worker._objects[ptr.id] = ptr
                state_ids.append(ptr.id)
            plan.replace_ids(plan.state_ids, state_ids)
            plan.state_ids = state_ids

        plan.replace_worker_ids(self.id, sy.hook.local_worker.id)
        return plan

    def connect(self):
        if self.__sio.eio.state != "connected":
            self.__sio.connect(self.uri)
            self.__sio.emit("/set-grid-id", {"id": self.id})

    def disconnect(self):
        self.__sio.disconnect()
