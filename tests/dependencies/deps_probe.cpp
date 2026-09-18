#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <zmq.hpp>
#include <czmq.h>
// CZMQ 4.0.2 exposes this legacy MSVC macro; keep it out of C++ headers.
#ifdef snprintf
#undef snprintf
#endif
#include <pugixml.hpp>
#include <SQLiteCpp/SQLiteCpp.h>
#include <boost/version.hpp>
#include <boost/filesystem.hpp>
#include <boost/regex.hpp>
#include <boost/system/error_code.hpp>
#include <boost/date_time/posix_time/posix_time.hpp>
#include <boost/geometry.hpp>
#include <boost/geometry/geometries/point_xy.hpp>
#include <boost/geometry/geometries/polygon.hpp>
#include <boost/graph/adjacency_list.hpp>
#include <boost/graph/dijkstra_shortest_paths.hpp>
#include <boost/dynamic_bitset.hpp>
#include <algorithm>
#include <cstring>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#if !defined(_M_X64) || !defined(_DLL) || !defined(_MT) || defined(_DEBUG)
#error Expected x64 Release dynamic CRT
#endif
static_assert(_MSVC_LANG == 201402L, "C++14 mode required");
static_assert(BOOST_VERSION == 107400, "Wrong Boost");
static_assert(ZMQ_VERSION == 40301, "Wrong ZeroMQ");
static_assert(CZMQ_VERSION == 40002, "Wrong CZMQ");
// Upstream v1.12.1 retains the public 1.12 API version macro.
static_assert(PUGIXML_VERSION == 1120, "Wrong pugixml API");
static_assert(SQLITE_VERSION_NUMBER == 3039004, "Wrong SQLite headers");
static_assert(SQLITECPP_VERSION_NUMBER == 1003001, "Wrong SQLiteCpp");

void require(bool value, const char* why) { if (!value) throw std::runtime_error(why); }
void bounded(zmq::socket_t& socket) {
    int timeout=3000, linger=0;
    socket.setsockopt(ZMQ_RCVTIMEO,&timeout,sizeof(timeout));
    socket.setsockopt(ZMQ_SNDTIMEO,&timeout,sizeof(timeout));
    socket.setsockopt(ZMQ_LINGER,&linger,sizeof(linger));
}
std::vector<unsigned char> frame(void* socket, bool more) {
    zframe_t* f=zframe_recv(socket);
    require(f!=NULL,"CZMQ receive failed/timeout");
    const bool flag=zframe_more(f)!=0;
    const unsigned char* data=zframe_data(f);
    std::vector<unsigned char> result;
    if(zframe_size(f)) result.assign(data,data+zframe_size(f));
    zframe_destroy(&f);
    require(flag==more,"Multipart boundary mismatch");
    return result;
}
struct NativeClient {
    SOCKET socket;
    NativeClient():socket(INVALID_SOCKET) { WSADATA data; require(WSAStartup(MAKEWORD(2,2),&data)==0,"WSAStartup"); }
    ~NativeClient() { if(socket!=INVALID_SOCKET) closesocket(socket); WSACleanup(); }
};
void check_zmq() {
    int major,minor,patch; zmq_version(&major,&minor,&patch);
    require(major==4 && minor==3 && patch==1,"Wrong linked ZeroMQ");
    require(zmq_has("curve")==1,"CURVE disabled");
    zmq::context_t context(1);
    zmq::socket_t left(context,ZMQ_PAIR),right(context,ZMQ_PAIR);
    bounded(left); bounded(right);
    left.bind("inproc://uxas-dependency-frames"); right.connect("inproc://uxas-dependency-frames");
    const unsigned char bytes[]={0,255,1,0,128,42};
    zmq::message_t binary(bytes,sizeof(bytes)),empty;
    require(left.send(binary,ZMQ_SNDMORE),"cppzmq send binary");
    require(left.send(empty),"cppzmq send empty");
    require(frame(static_cast<void*>(right),true)==std::vector<unsigned char>(bytes,bytes+sizeof(bytes)),"binary frame differs");
    require(frame(static_cast<void*>(right),false).empty(),"empty frame differs");
    zframe_t* reply=zframe_new(bytes,sizeof(bytes));
    require(reply!=NULL,"zframe_new");
    require(zframe_send(&reply,static_cast<void*>(right),ZFRAME_MORE)==0 && reply==NULL,"zframe_send ownership");
    reply=zframe_new(NULL,0);
    require(reply!=NULL && zframe_send(&reply,static_cast<void*>(right),0)==0 && reply==NULL,"zframe_send empty");
    zmq::message_t received;
    require(left.recv(&received),"cppzmq receive");
    require(received.size()==sizeof(bytes) && std::memcmp(received.data(),bytes,sizeof(bytes))==0,"reply differs");
    int more=0;size_t moreSize=sizeof(more);left.getsockopt(ZMQ_RCVMORE,&more,&moreSize);
    require(more==1 && left.recv(&received) && received.size()==0,"cppzmq multipart empty reply");
    left.getsockopt(ZMQ_RCVMORE,&more,&moreSize);require(more==0,"extra reply frame");

    zmq::socket_t stream(context,ZMQ_STREAM); bounded(stream);
    stream.bind("tcp://127.0.0.1:*");
    char endpoint[128]={0};size_t size=sizeof(endpoint);
    stream.getsockopt(ZMQ_LAST_ENDPOINT,endpoint,&size);
    std::string address(endpoint); const int port=std::stoi(address.substr(address.rfind(':')+1));
    NativeClient client;client.socket=::socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
    require(client.socket!=INVALID_SOCKET,"native socket");
    DWORD timeout=3000;
    setsockopt(client.socket,SOL_SOCKET,SO_RCVTIMEO,reinterpret_cast<const char*>(&timeout),sizeof(timeout));
    setsockopt(client.socket,SOL_SOCKET,SO_SNDTIMEO,reinterpret_cast<const char*>(&timeout),sizeof(timeout));
    sockaddr_in peer={};peer.sin_family=AF_INET;peer.sin_port=htons(static_cast<u_short>(port));peer.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    require(connect(client.socket,reinterpret_cast<sockaddr*>(&peer),sizeof(peer))==0,"TCP connect");
    const std::vector<unsigned char> identity=frame(static_cast<void*>(stream),true);
    require(!identity.empty() && frame(static_cast<void*>(stream),false).empty(),"STREAM connect event");
    require(send(client.socket,reinterpret_cast<const char*>(bytes),sizeof(bytes),0)==sizeof(bytes),"TCP send");
    std::vector<unsigned char> payload;
    while(payload.size()<sizeof(bytes)) {
        require(frame(static_cast<void*>(stream),true)==identity,"STREAM identity changed");
        const auto part=frame(static_cast<void*>(stream),false);
        require(!part.empty(),"unexpected disconnect");payload.insert(payload.end(),part.begin(),part.end());
    }
    require(payload==std::vector<unsigned char>(bytes,bytes+sizeof(bytes)),"STREAM payload differs");
    require(zmq_send(static_cast<void*>(stream),identity.data(),identity.size(),ZMQ_SNDMORE)==static_cast<int>(identity.size()),"STREAM reply identity");
    require(zmq_send(static_cast<void*>(stream),bytes,sizeof(bytes),0)==sizeof(bytes),"STREAM reply");
    unsigned char answer[sizeof(bytes)]={};size_t used=0;
    while(used<sizeof(answer)) { const int n=recv(client.socket,reinterpret_cast<char*>(answer+used),static_cast<int>(sizeof(answer)-used),0);require(n>0,"TCP reply receive");used+=n; }
    require(std::memcmp(answer,bytes,sizeof(bytes))==0,"TCP reply differs");
}
void check_pugi() {
    pugi::xml_document doc;
    require(doc.load_string("<x large='9007199254740993' max='9223372036854775807' min='-9223372036854775808' negative='-9007199254740993' empty='' bad='abc'/>") ,"XML parse");
    const auto x=doc.child("x");
    require(x.attribute("large").as_int64()==INT64_C(9007199254740993),"large ID");
    require(x.attribute("max").as_int64()==(std::numeric_limits<int64_t>::max)(),"int64 max");
    require(x.attribute("min").as_int64()==(std::numeric_limits<int64_t>::min)(),"int64 min");
    require(x.attribute("negative").as_int64()==-INT64_C(9007199254740993),"negative ID");
    require(x.attribute("missing").as_int64(INT64_C(9007199254740993))==INT64_C(9007199254740993),"missing default");
    require(x.attribute("empty").as_int64(123)==0 && x.attribute("bad").as_int64(123)==0,"original empty/invalid behavior changed");
}
void check_sqlite() {
    require(sqlite3_libversion_number()==3039004,"Wrong linked SQLite");
    require(sqlite3_threadsafe()==1 && sqlite3_compileoption_used("ENABLE_COLUMN_METADATA"),"SQLite compile options");
    const std::string filename="dependency-probe-"+std::to_string(GetCurrentProcessId())+".sqlite";
    const sqlite3_int64 id=INT64_C(9007199254740993);
    const unsigned char blob[]={0,255,1,128};
    {
        SQLite::Database db(filename,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE);
        db.exec("CREATE TABLE sample(id INTEGER PRIMARY KEY, text_value TEXT, bytes BLOB)");
        { SQLite::Transaction transaction(db);SQLite::Statement insert(db,"INSERT INTO sample VALUES(?,?,?)");
          insert.bind(1,id);insert.bind(2,std::string("UTF-8 \xe4\xb8\xad\xe6\x96\x87"));insert.bind(3,blob,sizeof(blob));require(insert.exec()==1,"insert");transaction.commit(); }
        { SQLite::Transaction rollback(db);db.exec("INSERT INTO sample VALUES(1,'rollback',NULL)"); }
    }
    {
        SQLite::Database db(filename,SQLITE_OPEN_READONLY);
        SQLite::Statement query(db,"SELECT id AS alias_id,text_value,bytes FROM sample");
        require(query.executeStep(),"persisted row missing");
        require(query.getColumn(0).getInt64()==id,"SQLite integer precision");
        require(std::string(query.getColumn(0).getOriginName())=="id","column metadata");
        require(std::string(query.getColumn(1).getText())=="UTF-8 \xe4\xb8\xad\xe6\x96\x87","UTF8 readback");
        require(query.getColumn(2).getBytes()==sizeof(blob) && std::memcmp(query.getColumn(2).getBlob(),blob,sizeof(blob))==0,"blob readback");
        require(!query.executeStep(),"rollback did not remove row");
    }
    require(DeleteFileA(filename.c_str())!=0,"database close/cleanup");
}
void check_boost() {
    require(boost::filesystem::exists(boost::filesystem::current_path()),"filesystem");
    require(boost::regex_match(std::string("UxAS-9007199254740993"),boost::regex("UxAS-[0-9]+")),"regex");
    boost::system::error_code ec=make_error_code(boost::system::errc::permission_denied);
    require(ec.value()!=0 && !ec.message().empty(),"system error code");
    const boost::posix_time::ptime t(boost::gregorian::date(2026,9,18));
    require(((t+boost::posix_time::seconds(123))-t).total_seconds()==123,"date_time");
    typedef boost::geometry::model::d2::point_xy<double> Point;
    boost::geometry::model::polygon<Point> polygon;
    boost::geometry::read_wkt("POLYGON((0 0,0 3,4 3,4 0,0 0))",polygon);
    require(boost::geometry::is_valid(polygon) && boost::geometry::area(polygon)==12.0,"geometry");
    typedef boost::adjacency_list<boost::vecS,boost::vecS,boost::undirectedS,boost::no_property,boost::property<boost::edge_weight_t,int> > Graph;
    Graph graph(3);add_edge(0,1,2,graph);add_edge(1,2,3,graph);add_edge(0,2,20,graph);
    std::vector<int> distances(3);
    boost::dijkstra_shortest_paths(graph,0,boost::distance_map(&distances[0]));
    require(distances[2]==5,"graph shortest path");
    boost::dynamic_bitset<> bits(130);bits.set(129);bits.set(64);
    require(bits.count()==2 && bits.test(129),"dynamic_bitset");
}
int main(int argc,char** argv) {
    try {
        require(argc==2,"component argument required");const std::string component(argv[1]);
        if(component=="timeout") { Sleep(10000);return 0; }
        if(component=="runtime") { std::cout<<"RUNTIME_READY"<<std::endl;Sleep(5000);return 0; }
        if(component=="zmq") check_zmq();else if(component=="pugi") check_pugi();
        else if(component=="sqlite") check_sqlite();else if(component=="boost") check_boost();
        else throw std::runtime_error("unknown component");
        std::cout<<"DEPS_OK "<<component<<" x64 MD c++14"<<std::endl;return 0;
    } catch(const std::exception& e) { std::cerr<<"DEPS_FAILED "<<e.what()<<std::endl;return 1; }
}
