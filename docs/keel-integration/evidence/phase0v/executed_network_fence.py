import socket
_connect=socket.socket.connect
_connect_ex=socket.socket.connect_ex
def blocked(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        raise RuntimeError("PHASE0V_OFFLINE_NETWORK_REFUSED")
    return _connect(self,address)
def blocked_ex(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        raise RuntimeError("PHASE0V_OFFLINE_NETWORK_REFUSED")
    return _connect_ex(self,address)
socket.socket.connect=blocked
socket.socket.connect_ex=blocked_ex
