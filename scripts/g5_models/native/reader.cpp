// Bounded, deliberately restricted static OSGB extraction. No rendering or network.
#include <osgDB/ReadFile>
#include <osgDB/Registry>
#include <osg/Geometry>
#include <osg/Geode>
#include <osg/Material>
#include <osg/Texture2D>
#include <osg/TriangleIndexFunctor>
#include <osg/Transform>
#include <osg/Version>
#include <osgUtil/Tessellator>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <cmath>
#include <sstream>

void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
std::string quote(const std::string& s){std::ostringstream o;o<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')o<<'\\'<<c;else if(c<32)o<<' ';else o<<c;}o<<'"';return o.str();}
struct Triangles {
    std::vector<unsigned> values;
    void operator()(unsigned a,unsigned b,unsigned c){values.insert(values.end(),{a,b,c});}
};
struct Reader:osg::NodeVisitor {
    std::string output;std::ofstream json;unsigned meshes=0;unsigned long long totalVertices=0;
    Reader(const std::string& path):NodeVisitor(TRAVERSE_ALL_CHILDREN),output(path),json(path+"/scene.json"){
        require(bool(json),"Cannot create output");json<<std::setprecision(17)<<"{\"schemaVersion\":1,\"osgVersion\":"<<quote(osgGetVersion())<<",\"meshes\":[";
    }
    void apply(osg::Node& n) override {require(!n.getUpdateCallback(),"Animated nodes are outside this static reader");traverse(n);}
    void apply(osg::Geode& geode) override {
        require(!geode.getUpdateCallback(),"Animated geode rejected");
        const auto world=osg::computeLocalToWorld(getNodePath());
        osg::Matrixd inverse;require(inverse.invert(world),"Singular transform");
        osg::ref_ptr<osg::StateSet> inherited=new osg::StateSet;
        for(auto* n:getNodePath())if(n->getStateSet())inherited->merge(*n->getStateSet());
        for(unsigned d=0;d<geode.getNumDrawables();++d){
            auto* g=geode.getDrawable(d)->asGeometry();require(g && !g->getUpdateCallback(),"Only static geometry is supported");
            std::vector<unsigned> originalModes;
            bool polygons=false;
            for(unsigned k=0;k<g->getNumPrimitiveSets();++k){auto mode=g->getPrimitiveSet(k)->getMode();originalModes.push_back(mode);polygons=polygons||mode==GL_POLYGON||mode==GL_QUADS||mode==GL_QUAD_STRIP;}
            if(polygons){osgUtil::Tessellator tess;tess.setTessellationType(osgUtil::Tessellator::TESS_TYPE_GEOMETRY);tess.retessellatePolygons(*g);}
            auto* vertices=dynamic_cast<osg::Vec3Array*>(g->getVertexArray());require(vertices && vertices->size()>0,"Missing float vertex array");
            auto* normals=dynamic_cast<osg::Vec3Array*>(g->getNormalArray());
            auto* uv=dynamic_cast<osg::Vec2Array*>(g->getTexCoordArray(0));
            require(!g->getColorArray(),"Vertex colors require explicit support");
            osg::ref_ptr<osg::StateSet> state=new osg::StateSet(*inherited,osg::CopyOp::SHALLOW_COPY);
            if(g->getStateSet())state->merge(*g->getStateSet());
            auto* material=dynamic_cast<osg::Material*>(state->getAttribute(osg::StateAttribute::MATERIAL));
            auto* texture=dynamic_cast<osg::Texture2D*>(state->getTextureAttribute(0,osg::StateAttribute::TEXTURE));
            osg::Vec4 diffuse=material?material->getDiffuse(osg::Material::FRONT):osg::Vec4(1,1,1,1);
            osg::TriangleIndexFunctor<Triangles> triangles;g->accept(triangles);
            require(!triangles.values.empty() && triangles.values.size()%3==0,"No triangles");
            totalVertices+=triangles.values.size();require(totalVertices<=3000000 && meshes<128,"Geometry exceeds conversion budget");
            const std::string id=std::to_string(meshes);std::ofstream binary(output+"/mesh-"+id+".f32",std::ios::binary);
            require(bool(binary),"Cannot create geometry output");
            for(size_t i=0;i<triangles.values.size();++i){
                const unsigned index=triangles.values[i];require(index<vertices->size(),"Index outside vertex array");
                const osg::Vec3d p=osg::Vec3d((*vertices)[index])*world;
                osg::Vec3d normal;
                if(normals && g->getNormalBinding()==osg::Geometry::BIND_PER_VERTEX){require(index<normals->size(),"Normal index invalid");normal=(*normals)[index];}
                else if(normals && g->getNormalBinding()==osg::Geometry::BIND_OVERALL){require(!normals->empty(),"Empty normal");normal=(*normals)[0];}
                else {auto a=(*vertices)[triangles.values[i/3*3]],b=(*vertices)[triangles.values[i/3*3+1]],c=(*vertices)[triangles.values[i/3*3+2]];normal=(b-a)^(c-a);}
                normal=osg::Matrixd::transform3x3(inverse,normal);normal.normalize();
                osg::Vec2 tex(0,0);if(uv){require(index<uv->size(),"UV index invalid");tex=(*uv)[index];}
                const float row[]={float(p.x()),float(p.y()),float(p.z()),float(normal.x()),float(normal.y()),float(normal.z()),tex.x(),tex.y()};
                for(float v:row)require(std::isfinite(v),"Nonfinite vertex");binary.write(reinterpret_cast<const char*>(row),sizeof(row));
            }
            require(bool(binary),"Geometry write failed");
            if(meshes)json<<',';
            json<<"{\"name\":"<<quote(g->getName())<<",\"vertices\":"<<triangles.values.size()<<",\"sourceVertices\":"<<vertices->size()<<",\"primitiveSets\":"<<g->getNumPrimitiveSets()<<",\"diffuse\":["<<diffuse.r()<<','<<diffuse.g()<<','<<diffuse.b()<<','<<diffuse.a()<<"],\"lightingMode\":"<<state->getMode(GL_LIGHTING)<<",\"sourcePrimitiveModes\":[";
            for(size_t k=0;k<originalModes.size();++k){if(k)json<<',';json<<originalModes[k];}json<<']';
            if(texture){
                auto* im=texture->getImage();require(im && im->data() && uv,"Texture data or coordinates missing");
                require(!im->isCompressed() && im->getDataType()==GL_UNSIGNED_BYTE && im->r()==1,"Only embedded uncompressed unsigned-byte 2D textures supported");
                require(im->s()>0&&im->t()>0&&im->s()<=4096&&im->t()<=4096,"Texture exceeds budget");
                std::ofstream pixels(output+"/image-"+id+".rgba",std::ios::binary);require(bool(pixels),"Cannot create texture output");
                unsigned transparent=0;
                // PNG/GLB rows start at top; OSG image origin is recorded, not guessed.
                for(int y=0;y<im->t();++y)for(int x=0;x<im->s();++x){
                    const int sourceY=im->getOrigin()==osg::Image::BOTTOM_LEFT?im->t()-1-y:y;auto color=im->getColor(x,sourceY);
                    unsigned char rgba[4];for(int k=0;k<4;++k)rgba[k]=static_cast<unsigned char>(std::round(std::max(0.f,std::min(1.f,color[k]))*255));
                    if(rgba[3]<255)++transparent;pixels.write(reinterpret_cast<const char*>(rgba),4);
                }
                require(bool(pixels),"Texture write failed");
                json<<",\"texture\":{\"sourceName\":"<<quote(im->getFileName())<<",\"width\":"<<im->s()<<",\"height\":"<<im->t()<<",\"origin\":"<<im->getOrigin()<<",\"transparentPixels\":"<<transparent<<",\"wrapS\":"<<texture->getWrap(osg::Texture::WRAP_S)<<",\"wrapT\":"<<texture->getWrap(osg::Texture::WRAP_T)<<"}";
            }
            json<<'}';++meshes;
        }
    }
    void finish(){require(meshes>0,"Model has no meshes");json<<"],\"expandedVertices\":"<<totalVertices<<",\"animations\":0}";json.close();require(bool(json),"JSON write failed");}
};
int main(int argc,char** argv){try{require(argc==3,"Usage: g5-model-reader source.osgb existing-output-directory");auto node=osgDB::readRefNodeFile(argv[1]);require(node.valid(),"OSGB read failed");Reader reader(argv[2]);node->accept(reader);reader.finish();return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
