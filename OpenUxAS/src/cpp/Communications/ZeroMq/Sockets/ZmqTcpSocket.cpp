// ===============================================================================
// Authors: AFRL/RQQA
// Organization: Air Force Research Laboratory, Aerospace Systems Directorate, Power and Control Division
// 
// Copyright (c) 2017 Government of the United State of America, as represented by
// the Secretary of the Air Force.  No copyright is claimed in the United States under
// Title 17, U.S. Code.  All Other Rights Reserved.
// ===============================================================================

#include "ZmqTcpSocket.h"
#include "UxAS_Log.h"

namespace uxas {
namespace communications {

ZmqTcpSocket::~ZmqTcpSocket() {
    UXAS_LOG_DEBUG_VERBOSE(typeid(this).name(),"::",__func__,":TRACE");
    // ZmqSocketBase closes this socket (linger=0), including every peer. The socket's
    // own routing ID is not a connected STREAM peer ID and cannot be used to disconnect.
}

}
}
