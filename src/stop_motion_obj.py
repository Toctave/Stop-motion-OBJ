# ##### BEGIN GPL LICENSE BLOCK #####
#
#   Stop motion OBJ: A Mesh sequence importer for Blender
#   Copyright (C) 2016-2021  Justin Jensen
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
import math
import os
import re
import glob
from bpy.app.handlers import persistent
from .version import *


def alphanumKey(string):
    """ Turn a string into a list of string and number chunks.
        "z23a" -> ["z", 23, "a"]
    """
    return [int(c) if c.isdigit() else c for c in re.split('([0-9]+)', string)]


def deselectAll():
    for ob in bpy.context.scene.objects:
        ob.select_set(state=False)


# We have to use this function instead of bpy.context.selected_objects because there's no "selected_objects" within the render context
def getSelectedObjects():
    selected_objects = []
    for ob in bpy.context.scene.objects:
        if ob.select_get() is True:
            selected_objects.append(ob)
    return selected_objects


def createUniqueMeshName(basename):
    attempts = 1
    uniqueName = basename
    while attempts < 1000 and uniqueName in bpy.data.meshes:
        uniqueName = "%s.%03d" % (basename, attempts)
        attempts += 1
    
    return uniqueName


def renderLockInterface():
    for scene in bpy.data.scenes:
        scene.render.use_lock_interface = True


# set the frame number for all mesh sequence objects
@persistent
def updateFrame(scene):
    scn = bpy.context.scene
    setFrameNumber(scn.frame_current)


# global variables
storedUseLockInterface = False
forceMeshLoad = False


@persistent
def renderInitHandler(scene):
    global storedUseLockInterface
    storedUseLockInterface = bpy.data.scenes["Scene"].render.use_lock_interface
    bpy.data.scenes["Scene"].render.use_lock_interface = True
    global forceMeshLoad
    forceMeshLoad = True


@persistent
def renderCompleteHandler(scene):
    renderStopped()


@persistent
def renderCancelHandler(scene):
    renderStopped()


def renderStopped():
    global storedUseLockInterface
    bpy.data.scenes["Scene"].render.use_lock_interface = storedUseLockInterface
    global forceMeshLoad
    forceMeshLoad = False


@persistent
def makeDirPathsRelative(scene):
    # if this .blend file hasn't been saved yet, quit
    if bpy.data.is_saved is False:
        return

    for obj in bpy.data.objects:
        mss = obj.mesh_sequence_settings
        if mss.initialized is True and mss.loaded is True:
            # if any are using relative paths that have not yet been relative-ized, then relative-ize them
            if mss.dirPathIsRelative is True and mss.dirPathNeedsRelativizing is True:
                newRelPath = bpy.path.relpath(mss.dirPath)
                mss.dirPath = newRelPath
                mss.dirPathNeedsRelativizing = False


# runs every time the start frame of an object is changed
def handlePlaybackChange(self, context):
    updateFrame(0)
    return None


# runs every time the cache size changes
def resizeCache(self, context):
    obj = context.object
    mss = obj.mesh_sequence_settings

    # if the cache size was changed to zero, we don't want to resize it
    if mss.cacheSize == 0:
        return None

    numMeshesToRemove = mss.numMeshesInMemory - mss.cacheSize
    for i in range(numMeshesToRemove):
        currentMeshIdx = getMeshIdxFromMeshKey(obj, obj.data.name)
        idxToDelete = nextCachedMeshToDelete(obj, currentMeshIdx)
        if idxToDelete >= 0:
            removeMeshFromCache(obj, idxToDelete)

    return None


def getMeshIdxFromMeshKey(obj, meshKey):
    for idx, meshNameItem in enumerate(obj.mesh_sequence_settings.meshNameArray):
        if meshNameItem.key == meshKey:
            return idx

    return -1

def countMatchingFiles(_directory, _filePrefix, _fileExtension):
    full_filepath = os.path.join(_directory, _filePrefix + '*.' + _fileExtension)
    files = glob.glob(full_filepath)
    return len(files)


def fileExtensionFromType(_type):
    if(_type == 'obj'):
        return 'obj'
    elif(_type == 'stl'):
        return 'stl'
    elif(_type == 'ply'):
        return 'ply'
    elif(_type == 'wrl'):
        return 'wrl'
    return ''


class SequenceVersion(bpy.types.PropertyGroup):
    # version number for the sequence. If the sequence doesn't already have a version, it will retain this legacy version
    versionMajor: bpy.props.IntProperty(name="Major Version", default=legacyScriptVersion[0])
    versionMinor: bpy.props.IntProperty(name="Minor Version", default=legacyScriptVersion[1])
    versionRevision: bpy.props.IntProperty(name="Revision Version", default=legacyScriptVersion[2])
    versionDevelopment: bpy.props.StringProperty(name="Development Version", default=legacyScriptVersion[3])

    def draw(self):
        pass

    def toString(self):
        mainVersionStr = str(self.versionMajor) + '.' + str(self.versionMinor) + '.' + str(self.versionRevision)
        if self.versionDevelopment == "":
            return mainVersionStr
        return mainVersionStr + '.' + self.versionDevelopment

class MeshImporter(bpy.types.PropertyGroup):
    # OBJ import parameters
    obj_use_edges: bpy.props.BoolProperty(name="Lines", description="Import lines and faces with 2 verts as edge", default=True)
    obj_use_smooth_groups: bpy.props.BoolProperty(name="Smooth Groups", description="Surround smooth groups by sharp edges", default=True)

    # There will come a day when we'll support multi-object sequences. But it is not this day.
    # obj_use_split_objects: bpy.props.BoolProperty(name="Object", description="Import OBJ Objects into Blender Objects", default=True)
    # obj_use_split_groups: bpy.props.BoolProperty(name="Group", description="Import OBJ Groups into Blender Objects", default=False)
    # obj_split_mode: bpy.props.EnumProperty(
    #     name="Split",
    #     items=(('ON', "Split", "Split geometry, omits unused vertices"),
    #            ('OFF', "Keep Vert Order", "Keep vertex order from file")))
    obj_use_groups_as_vgroups: bpy.props.BoolProperty(name="Poly Groups", description="Import OBJ groups as vertex groups", default=False)
    obj_use_image_search: bpy.props.BoolProperty(name="Image Search", description="Search subdirs for any associated images (Warning: may be slow)", default=True)
    obj_global_clamp_size: bpy.props.FloatProperty(
        name="Clamp Size",
        description="Clamp bounds under this value (zero to disable)",
        min=0.0,
        max=1000.0,
        soft_min=0.0,
        soft_max=1000.0,
        default=0.0)

    # STL import parameters
    stl_global_scale: bpy.props.FloatProperty(
        name="Scale",
        soft_min=0.001,
        soft_max=1000.0,
        min=1e-6,
        max=1e6,
        default=1.0)
    stl_use_scene_unit: bpy.props.BoolProperty(
        name="Scene Unit",
        description="Apply current scene's unit (as defined by unit scale) to imported data",
        default=False)
    stl_use_facet_normal: bpy.props.BoolProperty(
        name="Facet Normals",
        description="Use (import) facet normals (note that this will still give flat shading)",
        default=False)

    # (PLY has no import parameters)
    # Shared import parameters
    axis_forward: bpy.props.StringProperty(name="Axis Forward",default="-Z")
    axis_up: bpy.props.StringProperty(name="Axis Up",default="Y")

    def draw(self):
        pass

    def load(self, fileType, filePath):
        if fileType == 'obj':
            self.loadOBJ(filePath)
        elif fileType == 'stl':
            self.loadSTL(filePath)
        elif fileType == 'ply':
            self.loadPLY(filePath)
        elif fileType == 'wrl':
            self.loadWRL(filePath)

    def loadOBJ(self, filePath):
        # call the obj load function with all the correct parameters
        if bpy.app.version >= (2, 92, 0):
            bpy.ops.import_scene.obj(
                filepath=filePath,
                use_edges=self.obj_use_edges,
                use_smooth_groups=self.obj_use_smooth_groups,
                use_split_objects=False,
                use_split_groups=False,
                use_groups_as_vgroups=self.obj_use_groups_as_vgroups,
                use_image_search=self.obj_use_image_search,
                split_mode="OFF",
                global_clamp_size=self.obj_global_clamp_size,
                axis_forward=self.axis_forward,
                axis_up=self.axis_up)
        else:
            # Note the parameter called "global_clight_size", which is probably a typo
            #   It was corrected to "global_clamp_size" in Blender 2.92
            bpy.ops.import_scene.obj(
                filepath=filePath,
                use_edges=self.obj_use_edges,
                use_smooth_groups=self.obj_use_smooth_groups,
                use_split_objects=False,
                use_split_groups=False,
                use_groups_as_vgroups=self.obj_use_groups_as_vgroups,
                use_image_search=self.obj_use_image_search,
                split_mode="OFF",
                global_clight_size=self.obj_global_clamp_size,
                axis_forward=self.axis_forward,
                axis_up=self.axis_up)

    def loadSTL(self, filePath):
        # call the stl load function with all the correct parameters
        bpy.ops.import_mesh.stl(
            filepath=filePath,
            global_scale=self.stl_global_scale,
            use_scene_unit=self.stl_use_scene_unit,
            use_facet_normal=self.stl_use_facet_normal,
            axis_forward=self.axis_forward,
            axis_up=self.axis_up)
    
    def loadPLY(self, filePath):
        # call the ply load function with all the correct parameters
        bpy.ops.import_mesh.ply(filepath=filePath)

    def loadWRL(self, filePath):
        # call the WRL load function with all the correct parameters
        bpy.ops.import_scene.x3d(filepath=filePath)
        for obj in bpy.context.selected_objects:
            if obj.type != 'MESH':
                print('deleting ', obj)
                bpy.data.objects.remove(obj)


class MeshNameProp(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty()
    basename: bpy.props.StringProperty()
    inMemory: bpy.props.BoolProperty(default=False)


class MeshSequenceSettings(bpy.types.PropertyGroup):
    version: bpy.props.PointerProperty(type=SequenceVersion)
    fileImporter: bpy.props.PointerProperty(type=MeshImporter)

    dirPath: bpy.props.StringProperty(
        name="Root Folder",
        description="Only .OBJ files will be listed",
        subtype="DIR_PATH")
    fileName: bpy.props.StringProperty(name='File Name')
    dirPathIsRelative: bpy.props.BoolProperty(
        name="Relative Paths",
        description="Store relative paths for Streaming sequences and for reloading Cached sequences",
        default=False)

    dirPathNeedsRelativizing: bpy.props.BoolProperty(
        name="DirPath Needs Relativizing",
        description="Whether dirPath still needs to be converted into a relative path",
        default=False)

    # material mode (one material total or one material per frame)
    perFrameMaterial: bpy.props.BoolProperty(
        name='Material per Frame',
        default=False)

    # Whether to load the entire sequence into memory or to load meshes on-demand
    cacheMode: bpy.props.EnumProperty(
        items=[('cached', 'Cached', 'The full sequence is loaded into memory and saved in the .blend file'),
               ('streaming', 'Streaming', 'The sequence is loaded on-demand and not saved in the .blend file')],
        name='Cache Mode',
        default='cached')

    fileFormat: bpy.props.EnumProperty(
        items=[('obj', 'OBJ', 'Wavefront OBJ'),
               ('stl', 'STL', 'STereoLithography'),
               ('ply', 'PLY', 'Stanford PLY'),
               ('wrl', 'WRL', 'WRL file'),
               ],
        name='File Format',
        default='obj')

    startFrame: bpy.props.IntProperty(
        name='Start Frame',
        update=handlePlaybackChange,
        default=1)

    # TODO: deprecate meshNames in version 3.0.0. This will break backwards compatibility with version 2.0.2 and earlier
    meshNames: bpy.props.StringProperty()
    meshNameArray: bpy.props.CollectionProperty(type=MeshNameProp)
    numMeshes: bpy.props.IntProperty()
    numMeshesInMemory: bpy.props.IntProperty(default=0)
    initialized: bpy.props.BoolProperty(default=False)
    loaded: bpy.props.BoolProperty(default=False)

    # out-of-range frame mode
    frameMode: bpy.props.EnumProperty(
        items=[('0', 'Blank', 'Object disappears when frame is out of range'),
               ('1', 'Extend', 'First and last frames are duplicated'),
               ('2', 'Repeat', 'Repeat the animation'),
               ('3', 'Bounce', 'Play in reverse at the end of the frame range')],
        name='Mode',
        default='1',
        update=handlePlaybackChange)    

    # the number of frames to keep in memory if you're in streaming mode
    cacheSize: bpy.props.IntProperty(
        name='Cache Size',
        min=0,
        description='The maximum number of meshes to keep in memory. If >1, meshes will be removed from memory as new ones are loaded. If 0, all meshes will be kept.',
        update=resizeCache)

    # whether to enable/disable loading frames as they're required
    streamDuringPlayback: bpy.props.BoolProperty(
        name='Stream During Playback',
        description='Load meshes into memory as they are needed. If not checked, only the meshes currently in memory will appear.',
        default=True)

    speed: bpy.props.FloatProperty(
        name='Speed',
        min=0.0001,
        soft_min=0.01,
        step=25,
        precision=2,
        default=1,
        update=handlePlaybackChange)


@persistent
def initializeSequences(scene):
    for obj in bpy.data.objects:
        if obj.mesh_sequence_settings.initialized is True:
            loadSequenceFromBlendFile(obj)
    freeUnusedMeshes()


def deleteLinkedMeshMaterials(mesh, maxMaterialUsers=1, maxImageUsers=0):
    imagesToDelete = []
    materialsToDelete = []
    for meshMaterial in mesh.materials:
        materialsToDelete.append(meshMaterial)

        if hasattr(meshMaterial, "node_tree") and "Image Texture" in meshMaterial.node_tree.nodes:
            image = meshMaterial.node_tree.nodes['Image Texture'].image
            if image not in imagesToDelete:
                imagesToDelete.append(image)
    
    for materialToDelete in materialsToDelete:
        if materialToDelete.users <= maxMaterialUsers and materialToDelete.name in bpy.data.materials:
            bpy.data.materials.remove(materialToDelete)
    
    for imageToDelete in imagesToDelete:
        if imageToDelete.users <= maxImageUsers and imageToDelete.name in bpy.data.images:
            bpy.data.images.remove(imageToDelete)

    mesh.materials.clear()


def newMeshSequence():
    bpy.ops.object.add(type='MESH')
    # this new object should be the currently-selected object
    theObj = bpy.context.object
    theObj.name = 'sequence'
    theMesh = theObj.data
    theMesh.name = createUniqueMeshName('emptyMesh')
    theMesh.use_fake_user = True
    theMesh.inMeshSequence = True
    
    # add the mesh's name to the object's mesh_sequence_settings
    mss = theObj.mesh_sequence_settings
    emptyMeshNameElement = mss.meshNameArray.add()
    emptyMeshNameElement.key = theMesh.name
    emptyMeshNameElement.inMemory = True

    deselectAll()
    theObj.select_set(state=True)

    # set the current script version
    global currentScriptVersion
    mss.version.versionMajor = currentScriptVersion[0]
    mss.version.versionMinor = currentScriptVersion[1]
    mss.version.versionRevision = currentScriptVersion[2]
    mss.version.versionDevelopment = ""

    # if currentScriptVersion has four elements, set this to the fourth element
    if len(currentScriptVersion) == 4:
        mss.version.versionDevelopment = currentScriptVersion[3]

    mss.initialized = True

    # set Render > Lock Interface to true
    renderLockInterface()

    return theObj


def loadStreamingSequenceFromMeshFiles(obj, directory, filePrefix):
    # count the number of matching files
    mss = obj.mesh_sequence_settings
    absDirectory = bpy.path.abspath(directory)
    fileExtension = fileExtensionFromType(mss.fileFormat)
    if countMatchingFiles(absDirectory, filePrefix, fileExtension) == 0:
        return 0

    # load the first frame
    wildcardAbsPath = os.path.join(absDirectory, filePrefix + '*.' + fileExtension)
    numFrames = 0
    numFramesInMemory = 0
    unsortedFilenames = glob.glob(wildcardAbsPath)
    sortedFilenames = sorted(unsortedFilenames, key=alphanumKey)
    deselectAll()
    for filename in sortedFilenames:
        newMeshNameElement = mss.meshNameArray.add()
        newMeshNameElement.basename = os.path.basename(filename)
        newMeshNameElement.inMemory = False
        numFrames += 1

    mss.numMeshes = numFrames + 1
    mss.numMeshesInMemory = numFramesInMemory

    if numFrames > 0:
        mss.loaded = True
        setFrameObjStreamed(obj, bpy.context.scene.frame_current, True, False)
        obj.select_set(state=True)
    return numFrames


def loadSequenceFromMeshFiles(_obj, _dir, _file):
    full_dirpath = bpy.path.abspath(_dir)
    fileExtension = fileExtensionFromType(_obj.mesh_sequence_settings.fileFormat)

    # error out early if there are no files that match the file prefix
    if countMatchingFiles(full_dirpath, _file, fileExtension) == 0:
        return 0

    full_filepath = os.path.join(full_dirpath, _file + '*.' + fileExtension)
    numFrames = 0
    unsortedFiles = glob.glob(full_filepath)
    sortedFiles = sorted(unsortedFiles, key=alphanumKey)

    mss = _obj.mesh_sequence_settings

    deselectAll()
    for file in sortedFiles:
        # import the mesh file
        mss.fileImporter.load(mss.fileFormat, file)
        tmpObject = bpy.context.selected_objects[0]

        # IMPORTANT: don't copy it; just copy the pointer. This cuts memory usage in half.
        tmpMesh = tmpObject.data
        tmpMesh.use_fake_user = True
        tmpMesh.inMeshSequence = True
        deselectAll()
        tmpObject.select_set(state=True)
        bpy.ops.object.delete()

        # if this is not the first frame, remove any materials and/or images imported with the mesh
        if numFrames >= 1 and mss.perFrameMaterial is False:
            deleteLinkedMeshMaterials(tmpMesh)

        newMeshNameElement = mss.meshNameArray.add()
        newMeshNameElement.key = tmpMesh.name
        newMeshNameElement.basename = os.path.basename(file)
        newMeshNameElement.inMemory = True
        numFrames += 1

    mss.numMeshes = numFrames + 1
    mss.numMeshesInMemory = numFrames
    if(numFrames > 0):
        setFrameObj(_obj, bpy.context.scene.frame_current)

        _obj.select_set(state=True)
        mss.loaded = True

    return numFrames


# this is used when a mesh sequence object has been saved and subsequently found in a .blend file
def loadSequenceFromBlendFile(_obj):
    scn = bpy.context.scene
    mss = _obj.mesh_sequence_settings

    # if meshNames is not blank, we have an old file that must be converted to the new CollectionProperty format
    if mss.meshNames:
        # split meshNames
        # store them in mesh_sequence_settings.meshNameArray
        for meshName in mss.meshNames.split('/'):
            meshNameArrayElement = mss.meshNameArray.add()
            meshNameArrayElement.key = meshName
            meshNameArrayElement.inMemory = True

        # make sure the meshNames is not saved to the .blend file
        mss.meshNames = ''

    # count the number of mesh names (helps with backwards compatibility)
    mss.numMeshes = len(mss.meshNameArray)

    if mss.cacheMode == 'cached':
        mss.numMeshesInMemory = len(mss.meshNameArray) - 1
        # make sure the meshes know they're part of a mesh sequence (helps with backwards compatibility)
        for meshName in mss.meshNameArray:
            bpy.data.meshes[meshName.key].inMeshSequence = True
    elif mss.cacheMode == 'streaming':
        mss.numMeshesInMemory = 0

        # reset key and inMemory for meshes that were not saved in the .blend file
        for meshName in mss.meshNameArray:
            if not meshName.key.startswith('emptyMesh'):
                # if the mesh is not in memory, let's not pretend that it is
                if bpy.data.meshes.find(meshName.key) == -1:
                    meshName.key = ''
                    meshName.inMemory = False
                else:
                    mss.numMeshesInMemory += 1

    deselectAll()

    _obj.select_set(state=True)
    setFrameObj(_obj, scn.frame_current)
    mss.loaded = True


def reloadSequenceFromMeshFiles(_object, _directory, _filePrefix):
    # if there are no files that match the file prefix, error out early before making changes
    fileExtension = fileExtensionFromType(_object.mesh_sequence_settings.fileFormat)
    if countMatchingFiles(_directory, _filePrefix, fileExtension) == 0:
        return 0

    meshNamesArray = _object.mesh_sequence_settings.meshNameArray

    # mark the existing meshes for cleanup (keep the first 'emptyMesh' one)
    meshesToRemove = []
    for meshNameElement in meshNamesArray[1:]:
        bpy.data.meshes[meshNameElement.key].use_fake_user = False
        bpy.data.meshes[meshNameElement.key].inMeshSequence = False
        meshesToRemove.append(meshNameElement.key)

    # re-initialize _object.meshNameArray
    emptyMeshName = meshNamesArray[0].key
    meshNamesArray.clear()
    emptyMeshNameElement = meshNamesArray.add()
    emptyMeshNameElement.key = emptyMeshName

    # temporarily set the speed to 1 while we reload
    originalSpeed = _object.mesh_sequence_settings.speed
    _object.mesh_sequence_settings.speed = 1.0

    numMeshes = loadSequenceFromMeshFiles(_object, _directory, _filePrefix)

    _object.mesh_sequence_settings.numMeshes = numMeshes + 1
    _object.mesh_sequence_settings.numMeshesInMemory = numMeshes

    # set the speed back to its previous value
    _object.mesh_sequence_settings.speed = originalSpeed

    # remove the old meshes and materials from the scene
    for meshToRemove in meshesToRemove:
        removeMeshFromScene(meshToRemove, True)

    return numMeshes


def getMeshFromIndex(_obj, idx):
    key = _obj.mesh_sequence_settings.meshNameArray[idx].key
    return bpy.data.meshes[key]


def getMeshPropFromIndex(obj, idx):
    return obj.mesh_sequence_settings.meshNameArray[idx]


def setFrameNumber(frameNum):
    for obj in bpy.data.objects:
        mss = obj.mesh_sequence_settings
        if mss.initialized is True and mss.loaded is True:
            cacheMode = mss.cacheMode
            if cacheMode == 'cached':
                setFrameObj(obj, frameNum)
            elif cacheMode == 'streaming':
                global forceMeshLoad
                setFrameObjStreamed(obj, frameNum, forceLoad=forceMeshLoad, deleteMaterials=not mss.perFrameMaterial)


def getMeshIdxFromFrameNumber(_obj, frameNum):
    numRealMeshes = _obj.mesh_sequence_settings.numMeshes - 1

    # convert the frame number into a zero-based array index
    offsetFromStart = frameNum - _obj.mesh_sequence_settings.startFrame

    # adjust for playback speed
    scaledIdxFloat = offsetFromStart * _obj.mesh_sequence_settings.speed
    finalIdx = 0
    frameMode = _obj.mesh_sequence_settings.frameMode
    # 0: Blank
    if frameMode == '0':
        finalIdx = int(scaledIdxFloat)
        if(finalIdx < 0 or finalIdx >= numRealMeshes):
            finalIdx = -1
    # 1: Extend (default)
    elif frameMode == '1':
        finalIdx = int(scaledIdxFloat)
        if finalIdx < 0:
            finalIdx = 0
        elif finalIdx >= numRealMeshes:
            finalIdx = numRealMeshes - 1
    # 2: Repeat
    elif frameMode == '2':
        # shift the index into the positive domain; the math is easier to comprehend
        if scaledIdxFloat < 0:
            scaledIdxFloat += numRealMeshes * 10

        finalIdx = int(scaledIdxFloat % numRealMeshes)
    # 3: Bounce
    elif frameMode == '3':
        # shift the index into the positive domain; the math is easier to comprehend
        if scaledIdxFloat < 0:
            # this is not technically correct, but it's not really worth the hassle
            scaledIdxFloat += numRealMeshes * 100

        finalIdx = int(scaledIdxFloat) % numRealMeshes
        numCycles = int(int(scaledIdxFloat) / numRealMeshes)
        if(numCycles % 2 == 1):
            finalIdx = (numRealMeshes - 1) - finalIdx

    # account for the fact that everything is shifted by 1 because of "emptyMesh" at index 0
    return finalIdx + 1


def setFrameObj(_obj, frameNum):
    # store the current mesh for grabbing the material later
    prev_mesh = _obj.data
    idx = getMeshIdxFromFrameNumber(_obj, frameNum)
    next_mesh = getMeshFromIndex(_obj, idx)

    if (next_mesh != prev_mesh):
        # swap the meshes
        _obj.data = next_mesh

        if _obj.mesh_sequence_settings.perFrameMaterial is False:
            # if the previous mesh had a material, copy it to the new one
            if(len(prev_mesh.materials) > 0):
                _obj.data.materials.clear()
                for material in prev_mesh.materials:
                    _obj.data.materials.append(material)


def setFrameObjStreamed(obj, frameNum, forceLoad=False, deleteMaterials=False):
    mss = obj.mesh_sequence_settings
    idx = getMeshIdxFromFrameNumber(obj, frameNum)
    nextMeshProp = getMeshPropFromIndex(obj, idx)

    # if we want to load new meshes as needed and it's not already loaded
    if nextMeshProp.inMemory is False and (mss.streamDuringPlayback is True or forceLoad is True):
        importStreamedFile(obj, idx)
        if deleteMaterials is True:
            next_mesh = getMeshFromIndex(obj, idx)
            deleteLinkedMeshMaterials(next_mesh)

    # if the mesh is in memory, show it
    if nextMeshProp.inMemory is True:
        next_mesh = getMeshFromIndex(obj, idx)

        # store the current mesh for grabbing the material later
        prev_mesh = obj.data
        if next_mesh != prev_mesh:
            # swap the old one with the new one
            obj.data = next_mesh

            # if we need to, copy the materials from the old one onto the new one
            if obj.mesh_sequence_settings.perFrameMaterial is False:
                if len(prev_mesh.materials) > 0:
                    obj.data.materials.clear()
                    for material in prev_mesh.materials:
                        obj.data.materials.append(material)

    if mss.cacheSize > 0 and mss.numMeshesInMemory > mss.cacheSize:
        idxToDelete = nextCachedMeshToDelete(obj, idx)
        if idxToDelete >= 0:
            removeMeshFromCache(obj, idxToDelete)


def nextCachedMeshToDelete(obj, currentMeshIdx):
    mss = obj.mesh_sequence_settings

    # find and delete the one closest to the end of the array
    idxToDelete = len(mss.meshNameArray) - 1
    while idxToDelete > 0 and (idxToDelete == currentMeshIdx or mss.meshNameArray[idxToDelete].inMemory is False):
        idxToDelete -= 1
    
    return idxToDelete


# This function will be called from within both the Editor context and the Render context
# Keep that in mind when using bpy.context
def importStreamedFile(obj, idx):
    mss = obj.mesh_sequence_settings
    absDirectory = bpy.path.abspath(mss.dirPath)
    filename = os.path.join(absDirectory, mss.meshNameArray[idx].basename)
    deselectAll()
    mss.fileImporter.load(mss.fileFormat, filename)
    tmpObject = getSelectedObjects()[0]
    tmpMesh = tmpObject.data

    # we want to make sure the cached meshes are saved to the .blend file
    tmpMesh.use_fake_user = True
    tmpMesh.inMeshSequence = True
    deselectAll()
    tmpObject.select_set(state=True)
    bpy.data.objects.remove(tmpObject)
    mss.meshNameArray[idx].key = tmpMesh.name
    mss.meshNameArray[idx].inMemory = True
    mss.numMeshesInMemory += 1
    return tmpMesh


def removeMeshFromCache(obj, meshIdx):
    mss = obj.mesh_sequence_settings
    meshToRemoveKey = mss.meshNameArray[meshIdx].key
    removeMeshFromScene(meshToRemoveKey, mss.perFrameMaterial)
    mss.meshNameArray[meshIdx].inMemory = False
    mss.meshNameArray[meshIdx].key = ''
    mss.numMeshesInMemory -= 1


def removeMeshFromScene(meshKey, removeOwnedMaterials):
    if meshKey in bpy.data.meshes:
        meshToRemove = bpy.data.meshes[meshKey]
        if removeOwnedMaterials is True:
            # first delete any materials and image textures associated with the mesh
            deleteLinkedMeshMaterials(meshToRemove)
        
        meshToRemove.use_fake_user = False
        bpy.data.meshes.remove(meshToRemove)


def shadeSequence(_obj, smooth):
    deselectAll()
    _obj.select_set(state=True)
    # grab the current mesh so we can put it back later
    origMesh = _obj.data
    for idx in range(1, _obj.mesh_sequence_settings.numMeshes):
        _obj.data = getMeshFromIndex(_obj, idx)
        if(smooth):
            bpy.ops.object.shade_smooth()
        else:
            bpy.ops.object.shade_flat()
    # reset the sequence's mesh to the right one based on the current frame
    _obj.data = origMesh


def bakeSequence(_obj):
    scn = bpy.context.scene
    activeCollection = bpy.context.collection
    bpy.ops.object.empty_add(type='PLAIN_AXES')
    containerObj = bpy.context.active_object
    # rename the container object to "C_{object's current name}" ('C' stands for 'Container')
    newName = "C_" + _obj.name
    containerObj.name = newName

    # copy the object's transformation data into the container
    containerObj.location = _obj.location
    containerObj.scale = _obj.scale
    containerObj.rotation_euler = _obj.rotation_euler
    containerObj.rotation_quaternion = _obj.rotation_quaternion

    # copy the object's animation data into the container
    # http://blender.stackexchange.com/questions/27136/how-to-copy-keyframes-from-one-action-to-other
    if _obj.animation_data is not None:
        seq_anim = _obj.animation_data
        properties = [p.identifier for p in seq_anim.bl_rna.properties if not p.is_readonly]
        if containerObj.animation_data is None:
            containerObj.animation_data_create()
        container_anim = containerObj.animation_data
        for prop in properties:
            setattr(container_anim, prop, getattr(seq_anim, prop))

    # create a dictionary mapping meshes to new objects, meshToObject
    meshToObject = {}

    meshNameElements = _obj.mesh_sequence_settings.meshNameArray
    # for each mesh (including the empty mesh):
    for meshName in meshNameElements:
        currentMesh = bpy.data.meshes[meshName.key]
        # even though it's kinda still part of a mesh sequence, it's not really anymore
        currentMesh.inMeshSequence = False
        tmpObj = bpy.data.objects.new('o_' + currentMesh.name, currentMesh)
        activeCollection.objects.link(tmpObj)
        currentMesh.use_fake_user = False
        meshToObject[currentMesh] = tmpObj
        # in the object, add keyframes at frames 0 and the last frame of the animation:
        tmpObj.hide_viewport = True
        tmpObj.keyframe_insert(data_path='hide_viewport', frame=scn.frame_start)
        tmpObj.keyframe_insert(data_path='hide_viewport', frame=scn.frame_end)

        tmpObj.hide_render = True
        tmpObj.keyframe_insert(data_path='hide_render', frame=scn.frame_start)
        tmpObj.keyframe_insert(data_path='hide_render', frame=scn.frame_end)

        tmpObj.parent = containerObj

    # If this is a single-material sequence, make sure the material is copied to the whole sequence
    # This assumes that the first mesh in the sequence has a material
    if _obj.mesh_sequence_settings.perFrameMaterial is False:
        objMaterials = bpy.data.meshes[meshNameElements[1].key].materials
        meshesIter = iter(meshNameElements)
        # skip the emptyMesh
        next(meshesIter)
        # skip the first mesh (we'll copy the material from this one into the rest of them)
        next(meshesIter)
        for meshName in meshesIter:
            currentMesh = bpy.data.meshes[meshName.key]
            currentMesh.materials.clear()
            for material in objMaterials:
                currentMesh.materials.append(material)

    for frameNum in range(scn.frame_start, scn.frame_end + 1):
        # figure out which mesh is visible
        idx = getMeshIdxFromFrameNumber(_obj, frameNum)
        frameMesh = getMeshFromIndex(_obj, idx)

        # use the dictionary to find which object the mesh belongs to
        frameObj = meshToObject[frameMesh]

        # add two keyframes to the object at the current frame:
        frameObj.hide_viewport = False
        frameObj.keyframe_insert(data_path='hide_viewport', frame=frameNum)

        frameObj.hide_render = False
        frameObj.keyframe_insert(data_path='hide_render', frame=frameNum)

        # add two keyframes to the object at the next frame:
        frameObj.hide_viewport = True
        frameObj.keyframe_insert(data_path='hide_viewport', frame=frameNum + 1)

        frameObj.hide_render = True
        frameObj.keyframe_insert(data_path='hide_render', frame=frameNum + 1)

    # delete the sequence object
    deselectAll()
    _obj.select_set(state=True)
    bpy.ops.object.delete()


def deepDeleteSequence(obj):
    mss = obj.mesh_sequence_settings
    if mss.initialized is not True or mss.loaded is not True:
        return
    
    # make a list of all unique material and image texture used by any mesh in the sequence
    meshes = []
    materials = []
    images = []
    for meshName in mss.meshNameArray:
        # add unique meshes to the list
        if meshName.key not in meshes:
            meshes.append(meshName.key)

        if meshName.inMemory is True:
            mesh = bpy.data.meshes[meshName.key]
            for material in mesh.materials:
                # add unique materials to the list
                if material.name not in materials:
                    materials.append(material.name)
                
                # we're assuming the default import paradigm was used for creating materials:
                if hasattr(material, "node_tree") and "Image Texture" in material.node_tree.nodes:
                    imageKey = material.node_tree.nodes['Image Texture'].image.name
                    if imageKey not in images:
                        images.append(imageKey)

    # delete all meshes in the sequence
    for meshKey in meshes:
        if meshKey in bpy.data.meshes:
            bpy.data.meshes.remove(bpy.data.meshes[meshKey])
            
    # delete each material that no longer has any meshes referencing it
    for materialKey in materials:
        if materialKey in bpy.data.materials and bpy.data.materials[materialKey].users == 0:
            bpy.data.materials.remove(bpy.data.materials[materialKey])

    # delete each image that no longer has any materials referencing it
    for imageKey in images:
        if imageKey in bpy.data.images and bpy.data.images[imageKey].users == 0:
            bpy.data.images.remove(bpy.data.images[imageKey])


def freeUnusedMeshes():
    numFreed = 0
    for t_mesh in bpy.data.meshes:
        if t_mesh.inMeshSequence is True:
            t_mesh.use_fake_user = False
            numFreed += 1
    for t_obj in bpy.data.objects:
        mss = t_obj.mesh_sequence_settings
        if mss.initialized is True and mss.loaded is True:
            for t_meshName in mss.meshNameArray:
                if bpy.data.meshes.find(t_meshName.key) != -1:
                    bpy.data.meshes[t_meshName.key].use_fake_user = True
                    numFreed -= 1

    # the remaining meshes with no real or fake users will be garbage collected when Blender is closed
    print(numFreed, " meshes freed")


class ReloadMeshSequence(bpy.types.Operator):
    """Reload From Disk"""
    bl_idname = "ms.reload_mesh_sequence"
    bl_label = "Reload From Disk"
    bl_options = {'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, "You may reload a mesh sequence only while in Object mode")
            return {'CANCELLED'}

        obj = context.object
        dirPath = obj.mesh_sequence_settings.dirPath
        fileName = obj.mesh_sequence_settings.fileName

        num = reloadSequenceFromMeshFiles(obj, dirPath, fileName)
        if num == 0:
            self.report({'ERROR'}, "Invalid file path. Make sure the Root Folder, File Name, and File Format are correct.")
            return {'CANCELLED'}

        return {'FINISHED'}


class BatchShadeSmooth(bpy.types.Operator):
    """Smooth Shade Sequence"""
    bl_idname = "ms.batch_shade_smooth"
    bl_label = "Smooth"
    bl_options = {'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, "You may batch shade only while in Object mode")
            return {'CANCELLED'}

        obj = context.object
        # True for smooth
        shadeSequence(obj, True)
        return {'FINISHED'}


class BatchShadeFlat(bpy.types.Operator):
    """Flat Shade Sequence"""
    bl_idname = "ms.batch_shade_flat"
    bl_label = "Flat"
    bl_options = {'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, "You may batch shade only while in Object mode")
            return {'CANCELLED'}

        obj = context.object
        # False for flat
        shadeSequence(obj, False)
        return {'FINISHED'}


class BakeMeshSequence(bpy.types.Operator):
    """Bake Sequence"""
    bl_idname = "ms.bake_sequence"
    bl_label = "Bake Sequence"
    bl_options = {'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, "You may bake a sequence only while in Object mode")
            return {'CANCELLED'}

        obj = context.object
        bakeSequence(obj)
        # update the frame so the right shape is visible
        bpy.context.scene.frame_current = bpy.context.scene.frame_current
        return {'FINISHED'}


class DeepDeleteSequence(bpy.types.Operator):
    """Deep Delete Sequence"""
    bl_idname = "ms.deep_delete_sequence"
    bl_label = "Delete Sequence"
    bl_options = {'UNDO'}

    def execute(self, context):
        obj = context.object
        deepDeleteSequence(obj)
        return {'FINISHED'}

