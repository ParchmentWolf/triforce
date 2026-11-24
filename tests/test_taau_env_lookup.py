"""Actual-source TAAU key/full stand-in spy; GPU boundaries are spies, no Vulkan loader or performance measurement.

Use --emit-only FILE to stage C++ without invoking a compiler.
"""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    return source[start:start + re.search(r'^}', source[start:], re.M).end()]


def fixture(source, rule):
    # ((Triforce, 11-22, GPUWORK-20) taau_stand_in asks upscale_off.h which dispatches it stands in for: the header itself)
    return (PREFIX.replace('/*UPSCALE_OFF_H*/', rule.replace('#pragma once', '')) +
            block(source, 'bool taau_key(uint64_t key) {') + '\n' +
            block(source, 'bool taau_stand_in(VkCommandBuffer cmd,') + '\n' + SUFFIX)


PREFIX = r'''
#define _CRT_SECURE_NO_WARNINGS
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
static const char *configured_keys, *no_f16;
static int key_reads;
static const char* fixture_getenv(const char* name) {
    if (!strcmp(name, "RX_VK_TAAU_KEYS")) { ++key_reads; return configured_keys; }
    if (!strcmp(name, "RX_VK_NO_F16")) return no_f16;
    return nullptr;
}
#define getenv fixture_getenv
namespace Shader { namespace Backend { namespace SPIRV { static bool mma_software = true; } } }
using VkCommandBuffer = int;
using VkImageView = int;
constexpr int VK_IMAGE_VIEW_TYPE_2D=2, VK_FORMAT_B10G11R11_UFLOAT_PACK32=7, VK_FORMAT_UNDEFINED=0, VK_FORMAT_E5B9G9R9_UFLOAT_PACK32=9;
enum class ViewUse { Storage, Sample };
struct Desc { unsigned count=1; int format=23; };
struct Info { std::vector<Desc> texture_descriptors, image_descriptors; bool uses_cooperative_matrix=false; };
/*UPSCALE_OFF_H*/
/* ((Triforce, 11-22, GPUWORK-20) the upscaler Off, and the two gameplay networks by key, as vk_draw.cpp has them) */
static bool off_now;
static bool upscale_off_on(){return off_now;}
/* ((Triforce, 11-22, DESC-30) the lab's "diagold" phases, vk_draw.cpp: never here, so taau_key answers from its parsed list) */
static bool dispatch_diag_old(){return false;}
static bool gameplay_network(uint64_t key){return key==0xfd029a317a9a4b94ull || key==0x9dc98871eb7fc101ull;}
struct Stage { Info info; };
struct NvnState {};
struct Program { uint64_t key; std::vector<Stage> stages; };
struct Texture { int format=VK_FORMAT_B10G11R11_UFLOAT_PACK32; };
static Texture texture;
static Texture scene_texture{VK_FORMAT_E5B9G9R9_UFLOAT_PACK32};   /* (the network's input, asked for only for a network taken by its shape) */
static int sample_view_calls;
static struct { bool push_descriptor=false; } dev;
static bool vkCmdPushDescriptorSetKHR=true;
struct ImageInfo { VkImageView imageView; };
static struct DrawWork { std::vector<ImageInfo> imgs; } draw_work;
static DrawWork& dw() { return draw_work; }   // (vk_draw.cpp's dw is a TLS_OBJECT: the calling thread's, by a call)
static unsigned handle_value=5;
static bool resolve_image=true, upscale_result=true;
static int upscale_calls, view_calls, handle_calls;
static VkCommandBuffer forwarded_cmd;
static VkImageView forwarded_input,forwarded_output;
static Texture* forwarded_texture;
static uint32_t forwarded_level;
static uint64_t forwarded_key;
static std::string forwarded_text;
static bool forwarded_temporal;
static uint32_t handle_of(const NvnState&,const Stage&,const Desc&,uint32_t index){
    ++handle_calls;return index==0?handle_value:0;
}
static int image_format(int f){return f+100;}
static VkImageView texture_view_of(uint32_t handle,int type,ViewUse use,int format,Texture** out,uint32_t* level=nullptr){
    if(use==ViewUse::Sample){ ++sample_view_calls; if(handle==5 && type==VK_IMAGE_VIEW_TYPE_2D && format==VK_FORMAT_UNDEFINED) *out=&scene_texture; (void)level; return 98; }
    ++view_calls;
    if(handle!=5 || type!=VK_IMAGE_VIEW_TYPE_2D || use!=ViewUse::Storage || format!=123) return 0;
    *out=resolve_image?&texture:nullptr;*level=7;return 99;
}
/* (the recording lock of a parallel replay: taau_stand_in holds it around typed_upscale, whose pipeline and history images
   every recording thread shares) */
static int lock_depth;
struct ParLock { ParLock(){lock_depth++;} ~ParLock(){lock_depth--;} };
/* ((Triforce, FG-2) the picture it wrote, taken for frame generation after the upscale: outside the lock, when it drew) */
static int hudless_calls, hudless_lock_depth = -1;
static uint64_t hudless_key;
static void hudless_after_dispatch(VkCommandBuffer,uint64_t key){++hudless_calls;hudless_key=key;hudless_lock_depth=lock_depth;}
static bool typed_upscale(VkCommandBuffer cmd,VkImageView input,VkImageView output,Texture* out,uint32_t level,uint64_t key,const char* text,bool temporal){
    if(lock_depth<=0) return false;   /* (not under the lock: the upscale is refused, and the checks of its calls fail) */
    ++upscale_calls;forwarded_cmd=cmd;forwarded_input=input;forwarded_output=output;forwarded_texture=out;
    forwarded_level=level;forwarded_key=key;forwarded_text=text;forwarded_temporal=temporal;return upscale_result;
}
/* ((Triforce, 11-22, N64 Classic) its 3D pass on (vk_n64.cpp n64_3d_now), and the pass itself (vk_draw.cpp n64_upscale),
   spied as typed_upscale is: it too is refused outside the recording lock */
static bool n64_now;
static bool n64_3d_now(){return n64_now;}
static int n64_calls, n64_lock_depth=-1;
static const Texture* n64_input;
static VkImageView n64_in_view, n64_out_view;
static bool n64_upscale(VkCommandBuffer,VkImageView input,const Texture* in,VkImageView output,Texture* out,uint32_t level){
    if(lock_depth<=0) return false;
    ++n64_calls;n64_lock_depth=lock_depth;n64_input=in;n64_in_view=input;n64_out_view=output;forwarded_texture=out;
    forwarded_level=level;return upscale_result;
}
'''

SUFFIX = r'''
static unsigned failures=0;
static void check(bool ok,const char* what){if(!ok){++failures;fprintf(stderr,"FAIL: %s\n",what);}}
int main(int argc,char** argv){
    if(argc!=2)return 90;
    uint64_t target=0xfd029a317a9a4b94ull;bool expected=true;
    if(!strcmp(argv[1],"hardware"))Shader::Backend::SPIRV::mma_software=false,expected=false;
    else if(!strcmp(argv[1],"no-f16"))Shader::Backend::SPIRV::mma_software=false,no_f16="1";
    else if(!strcmp(argv[1],"empty"))configured_keys="",expected=false;
    else if(!strcmp(argv[1],"disabled"))configured_keys="-",expected=false;
    else if(!strcmp(argv[1],"custom"))configured_keys="0123456789abcdef",target=0x0123456789abcdefull;
    else if(!strcmp(argv[1],"prefixes"))configured_keys="abcd,fd029a";
    else if(!strcmp(argv[1],"off")){
        /* ((Triforce, 11-22, GPUWORK-20) the upscaler Off on a card that runs the networks: none is listed, every gameplay
           network is stood in for with the plain stretch, anything else is left alone */
        Shader::Backend::SPIRV::mma_software=false;
        dev.push_descriptor=true;dw().imgs={{11},{44}};
        NvnState state{};Stage stage;stage.info.texture_descriptors={{1,23}};stage.info.image_descriptors={{1,23}};
        auto run=[&](uint64_t key,bool matrix){Program q{key,{}};stage.info.uses_cooperative_matrix=matrix;q.stages.push_back(stage);
            forwarded_temporal=true;forwarded_text.clear();return taau_stand_in(19,state,q);};
        const uint64_t networks[]={0xfd029a317a9a4b94ull,0x9dc98871eb7fc101ull};
        const uint64_t shares[]={0x6676619641320ba7ull,0xf10782f9e58b6a7cull,0x72ba090c70fe2614ull,0x0775215f8da720e6ull};
        for(uint64_t k:networks)check(!run(k,true) && !upscale_calls,"with the upscaler not Off, a card that runs the networks stands in for none");
        for(uint64_t k:shares)check(!run(k,true) && !upscale_calls,"with the upscaler not Off, a share's network runs");
        check(sample_view_calls==0,"with the upscaler not Off, no network's input is looked up");
        off_now=true;
        int calls=0;
        for(uint64_t k:networks){
            check(run(k,true) && upscale_calls==++calls,"Off: a gameplay network by key is stood in for");
            check(!forwarded_temporal && forwarded_text=="the upscaler Off" && forwarded_key==k,"Off: the stretch is the plain one, no FXAA and no history bound");
            check(hudless_key==k,"Off: the picture is still taken for frame generation");
        }
        check(sample_view_calls==0,"Off: a network known by key needs no look at its input");
        for(uint64_t k:shares)check(run(k,true) && upscale_calls==++calls && !forwarded_temporal,"Off: a share's network (by its shape) is stood in for");
        check(sample_view_calls==4,"Off: a network taken by its shape has its input's format looked at");
        check(!run(0x1111111111111111ull,false) && upscale_calls==calls,"Off: a program that is no network is left alone");
        scene_texture.format=VK_FORMAT_B10G11R11_UFLOAT_PACK32;
        check(!run(shares[0],true) && upscale_calls==calls,"Off: a network of that shape whose input is not the scene's format is left alone");
        scene_texture.format=VK_FORMAT_E5B9G9R9_UFLOAT_PACK32;
        stage.info.texture_descriptors={{1,23},{1,23}};dw().imgs={{11},{12},{44}};
        check(!run(shares[0],true) && upscale_calls==calls,"Off: a network sampling two textures is left alone");
        check(run(networks[1],true) && upscale_calls==calls+1,"Off: a network known by key is taken whatever its shape");
        printf("%s failures=%u eligible=%d\n",argv[1],failures,upscale_calls);
        return failures?1:0;
    }
    else if(!strcmp(argv[1],"n64")){
        /* ((Triforce, 11-22, N64 Classic) its 3D pass on, on a card that runs the networks: every gameplay network, by key or
           by its shape, is drawn by it and not by the stretch, over the upscaler Off too; its input is looked at for the
           grid's size; the picture is still taken for frame generation; a program that is no network is left alone */
        Shader::Backend::SPIRV::mma_software=false;
        dev.push_descriptor=true;dw().imgs={{11},{44}};
        NvnState state{};Stage stage;stage.info.texture_descriptors={{1,23}};stage.info.image_descriptors={{1,23}};
        auto run=[&](uint64_t key,bool matrix){Program q{key,{}};stage.info.uses_cooperative_matrix=matrix;q.stages.push_back(stage);
            return taau_stand_in(19,state,q);};
        const uint64_t networks[]={0xfd029a317a9a4b94ull,0x9dc98871eb7fc101ull};
        const uint64_t shares[]={0x6676619641320ba7ull,0xf10782f9e58b6a7cull,0x72ba090c70fe2614ull,0x0775215f8da720e6ull};
        check(!run(networks[0],true) && !n64_calls && !upscale_calls,"N64 Classic off: none of it");
        n64_now=true;
        int calls=0;
        for(uint64_t k:networks){
            const int hud=hudless_calls;
            check(run(k,true) && n64_calls==++calls && !upscale_calls,"N64 Classic: a gameplay network by key is drawn by its 3D pass, not the stretch");
            check(n64_lock_depth==1 && n64_in_view==11 && n64_out_view==44 && n64_input==&scene_texture && forwarded_texture==&texture &&
                  forwarded_level==7,"N64 Classic: the network's input view and texture and its output, under the recording lock");
            check(hudless_calls==hud+1 && hudless_key==k && hudless_lock_depth==0,"N64 Classic: the picture is still taken for frame generation, outside the lock");
        }
        check(sample_view_calls==2,"N64 Classic: a network known by key has its input looked at, for the grid's size");
        for(uint64_t k:shares)check(run(k,true) && n64_calls==++calls && !upscale_calls,"N64 Classic: a share's network (by its shape) is drawn by its 3D pass");
        check(!run(0x1111111111111111ull,false) && n64_calls==calls,"N64 Classic: a program that is no network is left alone");
        scene_texture.format=VK_FORMAT_B10G11R11_UFLOAT_PACK32;
        check(!run(shares[0],true) && n64_calls==calls,"N64 Classic: a network of that shape whose input is not the scene's format is left alone");
        check(run(networks[0],true) && n64_calls==++calls,"N64 Classic: a network known by key is taken whatever its input's format");
        off_now=true;
        check(run(networks[1],true) && n64_calls==++calls && !upscale_calls,"N64 Classic over the upscaler Off");
        upscale_result=false;
        const int hud=hudless_calls;
        check(!run(networks[1],true) && hudless_calls==hud,"N64 Classic: when its pass draws nothing, nothing is taken and the game's network runs");
        printf("%s failures=%u eligible=%d\n",argv[1],failures,n64_calls);
        return failures?1:0;
    }
    else if(!strcmp(argv[1],"off-software")){
        /* (Off where the first network is already stood in for: Off's plain stretch, not the stand-in's FXAA) */
        dev.push_descriptor=true;dw().imgs={{11},{44}};off_now=true;
        NvnState state{};Stage stage;stage.info.texture_descriptors={{1,23}};stage.info.image_descriptors={{1,23}};
        Program q{0xfd029a317a9a4b94ull,{}};q.stages.push_back(stage);
        check(taau_stand_in(19,state,q) && !forwarded_temporal && forwarded_text=="the upscaler Off","Off wins over the listed stand-in's FXAA");
        off_now=false;
        check(taau_stand_in(19,state,q) && forwarded_temporal && forwarded_text=="fd029a317a9a4b94","not Off: the listed stand-in as before");
        printf("%s failures=%u eligible=%d\n",argv[1],failures,upscale_calls);
        return failures?1:0;
    }
    else if(strcmp(argv[1],"software"))return 91;
    check(taau_key(target)==expected && !taau_key(0),"existing key matcher unchanged");
    NvnState state{};Program program{target,{}};Stage stage;
    stage.info.texture_descriptors={{1,23},{2,23}};stage.info.image_descriptors={{1,23}};program.stages.push_back(stage);
    key_reads=0;
    check(!taau_stand_in(19,state,program),"capability rejection unchanged");
    check(key_reads==0,"first rejected invocation performs no key lookup after matcher priming");
    key_reads=0;
    for(int i=0;i<1000;i++)check(!taau_stand_in(19,state,program),"warm rejection unchanged");
    check(key_reads==0,"1000 warm rejected invocations perform no key lookup");
    check(handle_calls==0 && view_calls==0 && upscale_calls==0,"capability rejection avoids resource boundary calls");
    if(expected){
        dev.push_descriptor=true;dw().imgs={{11},{22},{33},{44}};
        auto rejected=[&](const char* what){key_reads=0;int prior=upscale_calls;check(!taau_stand_in(19,state,program),what);check(key_reads==0 && upscale_calls==prior,"rejected resource guard never reads/forwards keys");};
        vkCmdPushDescriptorSetKHR=false;rejected("missing push entry");vkCmdPushDescriptorSetKHR=true;
        auto stages=program.stages;program.stages.clear();rejected("empty stages");program.stages=stages;
        program.stages[0].info.texture_descriptors.clear();rejected("no textures");program.stages=stages;
        program.stages[0].info.image_descriptors.clear();rejected("no images");program.stages=stages;
        dw().imgs.pop_back();rejected("descriptor span too short");dw().imgs.push_back({44});
        dw().imgs[0].imageView=0;rejected("no input view");dw().imgs[0].imageView=11;
        dw().imgs[3].imageView=0;rejected("no output view");dw().imgs[3].imageView=44;
        handle_value=0;rejected("no handle");handle_value=5;
        resolve_image=false;rejected("no resolved image");resolve_image=true;
        texture.format=0;rejected("wrong output format");texture.format=VK_FORMAT_B10G11R11_UFLOAT_PACK32;
        check(hudless_calls==0,"a rejected invocation takes no picture for frame generation");
        auto accepted=[&](const char* text,bool result){
            key_reads=0;int prior=upscale_calls;upscale_result=result;
            const int hudless_before=hudless_calls;
            check(taau_stand_in(19,state,program)==result,"eligible helper result forwarded");
            check(hudless_calls==hudless_before+(result?1:0) && (!result || (hudless_key==target && hudless_lock_depth==0)),
                  "the picture it drew is taken for frame generation, outside the recording lock, and only when it drew");
            check(upscale_calls==prior+1 && key_reads==(configured_keys?2:1),"eligible invocation retains per-call lookup count");
            check(forwarded_cmd==19 && forwarded_input==11 && forwarded_output==44 && forwarded_texture==&texture && forwarded_level==7 && forwarded_key==target && forwarded_temporal,"eligible arguments preserved");
            check(forwarded_text==text,"current key text forwarded verbatim");
        };
        accepted(configured_keys?configured_keys:"fd029a317a9a4b94",true);
        configured_keys="later diagnostic override";accepted(configured_keys,false);
        configured_keys=nullptr;accepted("fd029a317a9a4b94",true);
    }
    printf("%s failures=%u eligible=%d\n",argv[1],failures,upscale_calls);
    return failures?1:0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT)
    p.add_argument('--cxx', default='clang++')
    p.add_argument('--emit-only', type=Path)
    p.add_argument('--cxx-arg', action='append', default=[], help='extra compiler/linker flag (repeatable)')
    args = p.parse_args()
    cpp = fixture((args.source / 'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8'),
                  (args.source / 'gpu/vk/upscale_off.h').read_text(encoding='utf-8'))
    if args.emit_only:
        with args.emit_only.open('x', encoding='utf-8') as f:
            f.write(cpp)
        print('STAGED ONLY:', args.emit_only)
        return
    with tempfile.TemporaryDirectory(prefix='taau-env-') as temp:
        folder = Path(temp)
        source, exe = folder / 'fixture.cpp', folder / 'fixture.exe'
        source.write_text(cpp, encoding='utf-8')
        if Path(args.cxx).name.lower() in ('cl', 'cl.exe', 'clang-cl', 'clang-cl.exe'):
            command = [args.cxx, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(source),
                       '/Fo' + str(folder / 'fixture.obj'), '/Fe' + str(exe), *args.cxx_arg]
        else:
            command = [args.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror', *args.cxx_arg, str(source), '-o', str(exe)]
        subprocess.run(command, cwd=folder, check=True)
        failed = False
        for case in ('software', 'hardware', 'no-f16', 'empty', 'disabled', 'custom', 'prefixes', 'off', 'off-software', 'n64'):
            result = subprocess.run([str(exe), case], cwd=folder)
            print(case, 'exit', result.returncode, flush=True)
            failed |= result.returncode != 0
        if failed:
            raise SystemExit(1)
    print('PASS: seven key configurations; rejected lookups removed, eligible per-call forwarding preserved; the upscaler Off; N64 Classic\'s 3D pass')


if __name__ == '__main__':
    main()
