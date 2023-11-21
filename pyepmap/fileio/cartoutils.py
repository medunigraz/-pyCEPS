# -*- coding: utf-8 -*-
# Created by Robert at 23.08.2023

import logging
import os
import zipfile
import re
import numpy as np
import xml.etree.ElementTree as xml
import scipy.spatial.distance as sp_distance

from pyepmap.datatypes.surface import Surface, SurfaceSignalMap, SurfaceLabel
from pyepmap.datatypes.cartotypes import PointForces
from pyepmap.utils import get_col_idx_from_header


logger = logging.getLogger(__name__)


def open_carto_file(filepath, pwd=None, mode='rb'):
    """Open a file within a Carto repository."""

    if isinstance(filepath, zipfile.Path):
        return filepath.open(mode=mode, pwd=pwd)

    return open(filepath, mode=mode)


def list_carto_dir(root, regex=''):
    """List contents of directory within Carto repository."""

    if isinstance(root, zipfile.Path):
        return [f.name for f in root.iterdir() if re.match(regex, f.name)]
    if root.endswith('.zip'):
        return [f.name for f in zipfile.Path(root).iterdir()
                if re.match(regex, f.name)]

    return [f for f in os.listdir(root) if re.match(regex, f)]


def join_carto_path(root, filepath):
    """Join a path within a Carto repository."""

    if isinstance(root, zipfile.Path):
        _, ext = os.path.splitext(filepath)
        # zipfile paths pointing to folders end with "/"
        filepath = filepath + '/' if filepath and not ext else filepath
        return root.joinpath(filepath)
    elif root.endswith('.zip'):
        # check if folder or file is requested
        # folder names in zipfile end with "/"
        _, ext = os.path.splitext(filepath)
        filepath = filepath + '/' if filepath and not ext else filepath
        try:
            return zipfile.Path(root, at=filepath)
        except FileNotFoundError:
            return root
        # return zipfile.Path(root, at=filepath)

    return os.path.join(root, filepath)


def carto_isfile(filepath):
    """Check if filepath points to existing file in Carto repository."""

    if isinstance(filepath, zipfile.Path):
        return filepath.exists() and filepath.is_file()

    return os.path.isfile(filepath)


def carto_isdir(path):
    """Check if path points to existing folder in Carto repository."""

    if isinstance(path, zipfile.Path):
        return path.exists() and path.is_dir()

    return os.path.isdir(path)


def read_mesh_file(filename, invisible_groups=False, encoding='cp1252'):
    """
    Read a CARTO3 mesh file.

    Non-active vertices and triangles with GroupID=-1000000 are removed.
    If no file is found, a Surface object with no points and triangles is
    returned.

    Parameters:
        filename : string
            path to *.mesh file
        invisible_groups : boolean (optional)
            If False only triangles with ID>=0 (visible groups) are
            imported, else all invisible groups with negative ID's are
            imported.
            ID's for vertices and triangles and also returned.
        encoding :

    Raises:
        ValueError : If end of sections is not recognized, i.e. no CRLF at end

    Returns:
        Surface object
        ndarray (n_verts, 1) optional : vertices ID
        ndarray (n_tris, 1) optional : triangles ID
    """

    # create child logger
    log = logging.getLogger('{}.read_mesh_file'.format(__name__))

    # create placeholders for surface map data
    n_verts = 0
    n_tris = 0
    verts = []
    verts_normals = []
    verts_group_id = []
    tris = []
    tris_normals = []
    tris_group_id = []
    verts_color_header = []
    verts_color = []
    verts_attr_header = []
    verts_attr_desc = []
    verts_attr = []

    with open_carto_file(filename, mode='rb') as fid:
        line = fid.readline().decode(encoding=encoding)
        if 'triangulatedmeshversion2.0' not in line.lower():
            log.warning('unexpected version number in Carto3 mesh file {}'
                        .format(filename))

        while True:
            line = fid.readline().decode(encoding=encoding)
            if not line:
                # either end of file or just a blank line.....
                break
            elif line.startswith('\r\n'):
                continue

            if line.startswith('NumVertex '):
                # space at end needed to not confuse with NumVertexColors
                n_verts = int(line.split('=')[1])
                log.debug('found {} vertices'.format(n_verts))

            elif line.startswith('NumTriangle '):
                n_tris = int(line.split('=')[1])
                log.debug('found {} triangles'.format(n_tris))

            elif line.startswith('[VerticesSection]'):
                log.debug('reading vertices section')
                # skip header line
                _ = fid.readline()
                # there is one blank line after header
                line = fid.readline().decode(encoding=encoding)
                if line != '\r\n':
                    raise ValueError('unexpected vertices section in Carto3 '
                                     'mesh file {}'.format(filename))

                verts = np.full((n_verts, 3), np.nan, dtype=float)
                verts_normals = np.full((n_verts, 3), np.nan, dtype=float)
                verts_group_id = np.full((n_verts, 1),
                                         np.iinfo(int).min,
                                         dtype=int)

                for i in range(n_verts):
                    line = fid.readline().decode(encoding=encoding)
                    values = line.split('=')[1].split()
                    verts[i, :] = np.array(values[0:3]).astype(float)
                    verts_normals[i, :] = np.array(values[3:6]).astype(float)
                    verts_group_id[i] = int(values[6])

                # next line must be blank
                line = fid.readline().decode(encoding=encoding)
                if line != '\r\n':
                    raise ValueError('unexpected end of vertices section in '
                                     'mesh file {}'.format(filename))

            elif line.startswith('[TrianglesSection]'):
                log.debug('reading triangles section')
                # skip header line
                _ = fid.readline()
                # there is one blank line after header
                line = fid.readline().decode(encoding=encoding)
                if line != '\r\n':
                    raise ValueError('unexpected triangles section in  '
                                     'mesh file {}'.format(filename))

                tris = np.full((n_tris, 3),
                               np.iinfo(int).min,
                               dtype=int)
                tris_normals = np.full((n_tris, 3),
                                       np.nan,
                                       dtype=float)
                tris_group_id = np.full((n_tris, 1),
                                        np.iinfo(int).min,
                                        dtype=int)

                for i in range(n_tris):
                    line = fid.readline().decode(encoding=encoding)
                    values = line.split('=')[1].split()
                    tris[i, :] = np.array(values[0:3]).astype(int)
                    tris_normals[i, :] = np.array(values[3:6]).astype(float)
                    tris_group_id[i] = int(values[6])

                # next line must be blank or EOF
                line = fid.readline().decode(encoding=encoding)
                if not line:
                    break
                if line != '\r\n':
                    raise ValueError('unexpected end of triangles '
                                     'section in mesh file {}'
                                     .format(filename))

            elif line.startswith('[VerticesColorsSection]'):
                log.debug('reading vertices color section')
                prev_line = line
                line = fid.readline().decode(encoding=encoding)
                while not line == '\r\n':
                    prev_line = line
                    line = fid.readline().decode(encoding=encoding)

                # line before empty line (data) contains header information
                verts_color_header = prev_line.split(';')[1].split()
                # check last header name, my contain 2 values
                if verts_color_header[-1].endswith(']'):
                    extra_header = verts_color_header[-1][:-1].split('[')
                    # remove old and append new
                    del verts_color_header[-1]
                    verts_color_header.extend(extra_header)
                # get number of color maps from header
                n_colors = len(verts_color_header)
                # get number of color maps from data
                last_pos = fid.tell()
                line = fid.readline().decode(encoding=encoding)
                n_values = len(line.split('=')[1].split())
                if not n_values == n_colors:
                    log.warning('VerticesColorSection header does not match '
                                'data, trying my best...')
                    n_colors = n_values
                fid.seek(last_pos)

                verts_color = np.full((n_verts, n_colors),
                                      np.nan,
                                      dtype=float)

                for i in range(n_verts):
                    line = fid.readline().decode(encoding=encoding)
                    verts_color[i, :] = np.array(line.split('=')[1].split()
                                                 ).astype(float)

                # next line must be blank
                line = fid.readline().decode(encoding=encoding)
                if line != '\r\n':
                    raise ValueError('unexpected end of vertices color '
                                     'section in mesh file {}'
                                     .format(filename))

            elif line.startswith('[VerticesAttributesSection]'):
                log.debug('reading vertices attributes section')

                # read comments, comments start with ;
                line = fid.readline().decode(encoding=encoding)
                verts_attr_desc = [line]
                while line.startswith(';'):
                    last_pos = fid.tell()
                    line = fid.readline().decode(encoding=encoding)
                    verts_attr_desc.append(line)

                # attribute description contain "=", header line not
                verts_attr_header = [comment for comment in verts_attr_desc
                                     if '=' not in comment][0]
                verts_attr_header = verts_attr_header.split(';')[1].split()
                # get number of attributes from header
                n_attr = len(verts_attr_header)

                verts_attr = np.full((n_verts, n_attr),
                                     np.iinfo(int).min,
                                     dtype=int)

                # now check if there is data
                if line:
                    # line is not empty, reset read pos and read rest of data
                    fid.seek(last_pos)

                    for i in range(n_verts):
                        line = fid.readline().decode(encoding=encoding)
                        verts_attr[i, :] = np.array(line.split('=')[1].split()
                                                    ).astype(bool)

    # build surface
    log.debug('build surface object')
    surface = Surface(verts, tris,
                      vertices_normals=verts_normals,
                      tris_normals=tris_normals)
    # build surface signal maps
    log.debug('build surface signal maps from mesh data')
    if len(verts_color) > 0:
        try:
            act_col = verts_color_header.index('LAT')
            bip_col = verts_color_header.index('Bipolar')
            uni_col = verts_color_header.index('Unipolar')
            imp_col = verts_color_header.index('Impedance')
            frc_col = verts_color_header.index('Force')
        except ValueError:
            log.warning('one or more headers for vertices colors '
                        'could not be extracted! Using best guess '
                        'for data columns...')
            act_col = 2
            bip_col = 1
            uni_col = 0
            imp_col = 3
            frc_col = 10

        try:
            description = 'Carto3 generated signal map'
            map_data = [
                SurfaceSignalMap(
                    'LAT_system',
                    np.expand_dims(verts_color[:, act_col], axis=1),
                    'pointData',
                    description=description
                ),
                SurfaceSignalMap(
                    'BIP_system',
                    np.expand_dims(verts_color[:, bip_col], axis=1),
                    'pointData',
                    description=description
                ),
                SurfaceSignalMap(
                    'UNI_system',
                    np.expand_dims(verts_color[:, uni_col], axis=1),
                    'pointData',
                    description=description
                ),
                SurfaceSignalMap(
                    'IMP_system',
                    np.expand_dims(verts_color[:, imp_col], axis=1),
                    'pointData',
                    description=description
                ),
                SurfaceSignalMap(
                    'FRC_system',
                    np.expand_dims(verts_color[:, frc_col], axis=1),
                    'pointData',
                    description=description
                )
            ]
        except Exception as err:
            log.warning('failed to import surface signal maps: {}'.format(err))

        # add maps to surface
        surface.add_signal_maps(map_data)

    # build surface labels
    log.debug('build surface labels')
    labels = [SurfaceLabel(name='vertices_group_id',
                           values=verts_group_id,
                           location='pointData',
                           description='invalid == -1000000'),
              SurfaceLabel(name='triangulation_group_id',
                           values=tris_group_id,
                           location='cellData',
                           description='non active == -1000000; '
                                       'invisible < 0')
              ]
    # add labels to surface
    surface.add_labels(labels)

    # build surface attributes and add them as labels to surface
    # TODO: is this useful information?
    # get attribute names from comments
    log.debug('build surface attribute labels')
    attributes = []
    for i in range(len(verts_attr_header)):
        attributes.append(
            SurfaceLabel(
                name=verts_attr_header[i],
                values=np.expand_dims(verts_attr[:, i], axis=1),
                location='pointData',
                description=verts_attr_desc
            )
        )
    if attributes:
        surface.add_labels(attributes)

    # check for unreferenced vertices and remove them
    verts_unref = 1 + np.argwhere(
        np.diff(np.unique(surface.tris.flatten())) > 1
    )
    if verts_unref.shape[0] > 0:
        log.info('found unreferenced vertices: {}'.format(verts_unref))
        surface.remove_vertices(verts_unref[:, 0])

    # check for invalid vertices and remove them
    verts_invalid = np.argwhere(verts_group_id == -1000000)
    if verts_invalid.shape[0] > 0:
        log.info('found {} invalid vertices, removing and renumbering '
                 'triangles...'.format(verts_invalid.shape[0]))
        surface.remove_vertices(verts_invalid[:, 0])

    # remove non-active triangles, this should be save now...
    tris_invalid = np.argwhere(tris_group_id == -1000000)
    if tris_invalid.shape[0] > 0:
        log.info('found {} invalid triangles, removing...'
                 .format(tris_invalid.shape[0]))
        surface.remove_tris(tris_invalid[:, 0])

    # remove invisible groups if not requested
    if not invisible_groups:
        # triangles with ID < 0 are invisible
        tris_id = surface.get_label('triangulation_group_id')
        tris_invisible = np.argwhere(tris_id.values < 0)
        if tris_invisible.shape[0] > 0:
            log.info('removing invisible groups...')
            surface.remove_tris(tris_invisible[:, 0])
            # TODO: What if no triangle has ID >= 0?
            if surface.tris.shape[0] < 1:
                log.warning('mesh has no visible triangle-groups!')

    return surface


def read_ecg_file_header(file, encoding='cp1252'):
    """
    Reads a Carto3 ECG file header.

    Returns:
        dict
            gain : float
                scale factor of value
            name_bip : string
                bipolar channel name
            name_uni : string
                unipolar channel name
            name_ref : string
                reference channel name
            ecg_names : list of string
                channel names in file
            header_lines : int
                number of header lines
    """

    SUPPORTED_VERSIONS = ['ecg_export_4.0', 'ecg_export_4.1']

    # create child logger
    log = logging.getLogger('{}.read_ecg_file_header'.format(__name__))
    log.debug('reading ecg file header in {}'.format(file))

    file_header = {'version': '',
                   'gain': np.nan,
                   'name_bip': '',
                   'name_uni': '',
                   'name_ref': '',
                   'ecg_names': [],
                   'header_lines': 0}

    # if not os.path.isfile(file):
    if not carto_isfile(file):
        log.info('ecg file {} not found'.format(file))
        return file_header

    with open_carto_file(file, mode='rb') as f:
        # read file version
        version = f.readline().decode(encoding=encoding).rstrip()
        if not version.lower() in SUPPORTED_VERSIONS:
            log.info('version in file {} is not supported'.format(file))
            return file_header
        file_header['version'] = version.split('_')[-1]
        file_header['header_lines'] = file_header['header_lines'] + 1

        # read gain
        line = f.readline().decode(encoding=encoding).rstrip()
        if not line.lower().startswith('raw'):
            log.warning('unexpected header line (2) in {}'.format(file))
        file_header['header_lines'] = file_header['header_lines'] + 1
        file_header['gain'] = float(line.lower().split('=')[1])
        if not file_header['gain'] == 0.003:
            log.warning('unexpected gain ({}) in file {}'
                        .format(file_header['gain'], file))

        # read mapping channels
        if file_header['version'] == '4.0':
            # channel names are included up to version 4.0
            line = f.readline().decode(encoding=encoding).rstrip()
            if not line.lower().startswith('unipolar'):
                log.warning('unexpected header line (3) in {}, trying next'
                            .format(file))
                line = f.readline().decode(encoding=encoding).rstrip()
                if not line.lower().startswith('unipolar'):
                    log.info('unexpected file header in {}'.format(file))
                    return file_header
                file_header['header_lines'] = file_header['header_lines'] + 1
            file_header['header_lines'] = file_header['header_lines'] + 1

            uni_token = 'unipolar mapping channel='
            bip_token = 'bipolar mapping channel='
            ref_token = 'reference channel='

            str_start = line.lower().find(uni_token) + len(uni_token)
            str_end = line.lower().find(bip_token)
            file_header['name_uni'] = line[str_start:str_end].strip()

            str_start = line.lower().find(bip_token) + len(bip_token)
            str_end = line.lower().find(ref_token)
            file_header['name_bip'] = line[str_start:str_end].strip()

            str_start = line.lower().find(ref_token) + len(ref_token)
            file_header['name_ref'] = line[line.lower().find(ref_token)
                                           + len(ref_token):].split()[0].strip()
            # TODO: compare this to MATLAB version, i.e. uni2 name??

        # read column names
        line = f.readline().decode(encoding=encoding).rstrip()
        file_header['ecg_names'] = ['{})'.format(x.strip())
                                    for x in line.split(')')]
        # remove last occurrence of ")"
        if file_header['ecg_names'][-1] == ')':
            file_header['ecg_names'].pop()

        file_header['header_lines'] = file_header['header_lines'] + 1

    return file_header


def read_ecg_file(file, column_indices=None, skip_rows=None,
                  encoding='cp1252'):
    """
    Read data from a Carto3 ECG file.

    Parameters:
        file : string
            path to the ECG file
        column_indices : list of int
            data columns to import
        skip_rows : int
            number of header lines to skip
        encoding :

    Raises:
        ValueError : If number of data points per channel is not 2500

    Returns:
        ndarray (2500, n_channels)
    """

    # create child logger
    log = logging.getLogger('{}.read_ecg_file'.format(__name__))
    log.debug('reading ecg file {}'.format(file))

    if not carto_isfile(file):
        log.info('ecg file {} not found'.format(file))
        return np.array([], dtype=np.int32)

    if not skip_rows:
        ecg_header = read_ecg_file_header(file, encoding=encoding)
        skip_rows = ecg_header['header_lines']

    if isinstance(file, zipfile.Path):
        data = np.loadtxt(file.open(),
                          dtype=np.float32,  # int in files, but converted to float
                          skiprows=skip_rows,
                          usecols=column_indices)
    else:
        data = np.loadtxt(file,
                          dtype=np.float32,  # int in files, but converted to float
                          skiprows=skip_rows,
                          usecols=column_indices)

    if not data.shape[0] == 2500:
        log.error('unexpected size of emg data in {}'.format(file))
        raise ValueError

    return data


def channel_names_from_ecg_header(ecg_header):
    """
    Get channel names for BIP, UNI and REF traces from file header.

    This function also tries to extract the name of the second unipolar
    channel from the bipolar channel name.

    Parameters:
        ecg_header : dict
            header info returned from read_ecg_file_header()

    Returns:
        bip_name : string
            bipolar channel name
        uni_name : list of string
            unipolar channel names
        ref_name : string
            reference channel name
    """

    bip_name = ecg_header['name_bip']
    uni_name = [ecg_header['name_uni'], ecg_header['name_uni']]
    ref_name = ecg_header['name_ref']

    if ecg_header['name_bip'].startswith('MCC'):
        # Channels name differs from header info for MEC
        # MEC connector names have different naming convention
        uni_name[0] = ecg_header['name_uni']
        # TODO: fix second unipolar channel name for MCC Ablation
        uni_name[1] = uni_name[0]

    else:
        # get unipolar names from bipolar electrode names
        try:
            connector, channels = ecg_header['name_bip'].split('_')
            channel_num = channels.split('-')
            uni_name[0] = connector + '_' + channel_num[0]
            uni_name[1] = connector + '_' + channel_num[1]
        except ValueError:
            # some connectors don't add the connector name at beginning
            channel_names = ecg_header['name_bip'].split('-')
            uni_name[0] = channel_names[0]
            uni_name[1] = channel_names[1]

    return bip_name, uni_name, ref_name


def channel_names_from_pos_file(point, study_root='',
                                encoding='cp1252'):
    """
    Get channel names for BIP, UNI and REF traces from electrode positions.

    Extracted names are compared to EGM names in CARTO point ECG file. If
    discrepancies are found, the names from the ECG files are used.

    Parameters:
        point : CartoPoint object
        study_root : string
            path to the study's root directory
        encoding :

    Returns:
        bip_name : string
            bipolar channel name
        uni_name : list of string
            unipolar channel names
        ref_name : string
            reference channel name
        uni_coordinates : ndarray (3, 2)
            cartesian coordinates of the unipolar recording electrodes
    """

    # create child logger
    log = logging.getLogger('{}.check_egm_names'.format(__name__))

    # read points XML file
    with open_carto_file(join_carto_path(study_root, point.pointFile)) as fid:
        root = xml.parse(fid).getroot()

    log.debug('getting electrode names for point {}'.format(point.name))

    # find which electrode has collected the point
    position_files = []
    for connector in root.find('Positions').findall('Connector'):
        connector_file = list(connector.attrib.values())[0]
        if connector_file.lower().endswith(
                'ectrode_positions_onannotation.txt'):
            position_files.append(connector_file)
    position_files = [join_carto_path(study_root, x) for x in position_files]

    bipName, uniName, xyz_2 = get_egm_name_from_pos(point.X,
                                                    position_files,
                                                    encoding=encoding)
    uniCoordinates = np.stack((point.X, xyz_2), axis=-1)

    # now check the name of the electrode identified above by
    # comparing with the ECG_Export file
    ecgFile = root.find('ECG').get('FileName')
    ecg_header = read_ecg_file_header(join_carto_path(study_root, ecgFile),
                                      encoding=encoding)
    refName = ecg_header['name_ref']

    if not ecg_header['name_bip'] == bipName:
        msg = ('Conflict: bipolar electrode name "{}" from position file '
               'does not match electrode name "{}" in ECG file!\n'
               'Using name from ECG file for point {}.'
               ).format(bipName,
                        ecg_header['name_bip'],
                        root.get('ID'))
        log.warning(msg)
        bipName = ecg_header['name_bip']

    if not ecg_header['name_uni'] == uniName[0]:
        msg = ('Conflict: unipolar electrode name "{}" from position '
               'file does not match electrode name "{}" in ECG file!\n'
               'Using name from ECG file for point {}.'
               ).format(uniName[0],
                        ecg_header['name_uni'],
                        root.get('ID'))
        log.warning(msg)

        if ecg_header['name_bip'].startswith('MCC'):
            # Channels name differs from header info for MEC
            # MEC connector names have different naming convention
            uniName[0] = ecg_header['name_uni']
            # TODO: fix second unipolar channel name for MCC Ablation
            uniName[1] = uniName[0]

        else:
            # get unipolar names from bipolar electrode names
            try:
                connector, channels = ecg_header['name_bip'].split('_')
                channel_num = channels.split('-')
                uniName[0] = connector + '_' + channel_num[0]
                uniName[1] = connector + '_' + channel_num[1]
            except ValueError:
                # some connectors dont add the connector name at beginning
                channel_names = ecg_header['name_bip'].split('-')
                uniName[0] = channel_names[0]
                uniName[1] = channel_names[1]

            # final check
            if not uniName[0] == ecg_header['name_uni']:
                log.warning('failed to extract unipolar electrode name '
                            'from bipolar electrode name, using ECG file '
                            'header info instead! "{}/{} using {}"'
                            .format(uniName[0],
                                    ecg_header['name_bip'],
                                    ecg_header['name_uni']))
                uniName[0] = ecg_header['name_uni']
                uniName[1] = uniName[0]

    return bipName, uniName, refName, uniCoordinates


def get_egm_name_from_pos(point_xyz, position_files,
                          encoding='cp1252'):
    """
    Find electrode that recorded Point at xyz.

    This function also tries to identify the name and coordinates of the
    second unipolar channel which made the bipolar recording.

    Parameters:
        point_xyz : ndarray (3, 1)
            coordinates of the point
        position_files : list of string
            path to the position files
        encoding :

    Returns:
         egm_name_bip : string
            name of the bipolar channel
        egm_name_uni : list of string
            names of the unipolar channels
        xyz_2 : ndarray (3, 1)
            coordinates of the second unipolar channel
    """

    # create child logger
    log = logging.getLogger('{}.get_egm_name_at_point'.format(__name__))
    log.debug('find electrode that recorded point(s) at {}'.format(point_xyz))

    egm_name_bip = None
    egm_name_uni = [None, None]
    xyz_2 = np.full(3, np.nan, dtype=np.float32)

    electrode_cols = ['Electrode#', 'Time', 'X', 'Y', 'Z']
    sensor_cols = ['Sensor#', 'Time', 'X', 'Y', 'Z']

    min_dist = np.inf
    closest_file = []
    closest_electrode = []

    for file in position_files:
        if not carto_isfile(file):
            log.info('position file {} not found'.format(file))
            continue

        with open_carto_file(file, mode='rb') as f:
            # reader file format info
            line = f.readline().decode(encoding=encoding)
            if not line.rstrip().lower().endswith('_positions_2.0'):
                log.info('version number of position file {} is not supported'
                         .format(file))
                continue
            # read header info
            line = f.readline().decode(encoding=encoding)
            columns = re.split(r'\t+', line.rstrip('\t\r\n'))
            if not columns == electrode_cols and not columns == sensor_cols:
                log.info('unexpected column names in position file {}'
                         .format(file))
                continue

        if isinstance(file, zipfile.Path):
            data = np.loadtxt(file.open(),
                              dtype=np.float32,
                              skiprows=2,
                              )
        else:
            data = np.loadtxt(file,
                              dtype=np.float32,
                              skiprows=2,
                              )
        xyz = data[:, [2, 3, 4]]
        electrode_idx = data[:, 0].astype(int)

        if 'MEC' in file.name if isinstance(file, zipfile.Path) else file:
            # positions of last 3 electrodes is always identical
            xyz = xyz[:-3]
            electrode_idx = electrode_idx[:-3]

        dist = sp_distance.cdist(xyz, np.array([point_xyz])).flatten()
        idx_closest = np.argwhere(dist == np.amin(dist)).flatten()

        if idx_closest.size > 1:
            log.debug('found multiple electrodes with same minimum '
                      'distance in file {}. Trying next file'.format(file))
            continue

        idx_closest = idx_closest[0]
        if dist[idx_closest] < min_dist:
            min_dist = dist[idx_closest]
            closest_electrode = translate_connector_index(
                electrode_idx,
                idx_closest,
                file.name if isinstance(file, zipfile.Path) else file)
            closest_file = os.path.basename(
                file.name if isinstance(file, zipfile.Path) else file)
            try:
                xyz_2 = xyz[idx_closest+1, :]
            except IndexError:
                # TODO: point was recorded from last electrode,
                #  so second unipolar electrogram is the one BEFORE?
                log.warning('coordinates for second unipolar channel: '
                            'index out of range! This should not have '
                            'happened...')
                # xyz_2 = xyz[idx_closest-1, :]

    if not closest_file or not closest_electrode:
        log.warning('unable to find which electrode recorded point at {}!'
                    .format(point_xyz))
        return egm_name_bip, egm_name_uni, xyz_2

    # now we have to translate the filename into the egm name that gives us
    # the correct egm in the ECG_Export file.
    identifier = ['CS_CONNECTOR',
                  'MAGNETIC_20_POLE_A_CONNECTOR',
                  'MAGNETIC_20_POLE_B_CONNECTOR',
                  'NAVISTAR_CONNECTOR',
                  'MEC']
    translation = ['CS',
                   '20A_',
                   '20B_',
                   'M',
                   'MCC Abl BiPolar']

    idx_identifier = [identifier.index(x) for x in identifier
                      if x in closest_file][0]
    egm_name = translation[idx_identifier]

    if egm_name == 'MCC Abl BiPolar':
        egm_name_bip = egm_name + ' {}'.format(closest_electrode)
        egm_name_uni[0] = 'M{}'.format(closest_electrode)
        egm_name_uni[1] = egm_name_uni[0]

    elif egm_name == '20A_' or egm_name == '20B_':
        egm_name_bip = '{}{}-{}'.format(egm_name,
                                        closest_electrode,
                                        closest_electrode + 1)
        egm_name_uni[0] = '{}{}'.format(egm_name, closest_electrode)
        egm_name_uni[1] = '{}{}'.format(egm_name, closest_electrode + 1)
        # TODO: why is this done??
        if egm_name_bip == '20B_7-8':
            egm_name_bip = '20B_9-8'

    else:
        egm_name_bip = '{}{}-{}{}'.format(egm_name,
                                          closest_electrode,
                                          egm_name,
                                          closest_electrode + 1)
        egm_name_uni[0] = '{}{}'.format(egm_name, closest_electrode)
        egm_name_uni[1] = '{}{}'.format(egm_name, closest_electrode + 1)

    return egm_name_bip, egm_name_uni, xyz_2


def translate_connector_index(index_list, index, file_name):
    """
    Translate connector index in electrode position file to channel number
    in ecg file.
    """

    CONNECTORS = ['MAGNETIC_20_POLE_A_CONNECTOR',
                  'MAGNETIC_20_POLE_B_CONNECTOR']
    LASSO_INDEXING = [1, 2, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4,
                      1, 2, 3, 4]
    PENTA_INDEXING = [1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13,
                      14, 15, 16, 17, 18, 19, 20, 21, 22]
    # TODO: implement correct indexing for CS catheter
    CS_INDEXING = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    closest_electrode = -1

    if any([x in file_name for x in CONNECTORS]):
        if np.array_equal(index_list, LASSO_INDEXING):
            # two electrodes offset and 1-based numbering
            closest_electrode = index - 2 + 1
        elif np.array_equal(index_list, PENTA_INDEXING):
            closest_electrode = index_list[index]
        else:
            # some other catheter was connected, try best guess
            closest_electrode = index_list[index]
    else:
        closest_electrode = index_list[index]

    return closest_electrode


def read_force_file(file, encoding='cp1252'):
    """
    Reads a Carto3 point force file.

    Parameters:
        file : string
            path to force file

    Returns:
        PointForces object
    """

    # create child logger
    log = logging.getLogger('{}.read_force_file'.format(__name__))
    log.debug('reading force file {}'.format(file))

    force_data = {'force': np.nan,
                  'axialAngle': np.nan,
                  'lateralAngle': np.nan,
                  't_time': np.empty(0),
                  't_force': np.empty(0),
                  't_axialAngle': np.empty(0),
                  't_lateralAngle': np.empty(0),
                  'systemTime': np.empty(0)}

    if not carto_isfile(file):
        log.warning('force file {} not found'.format(file))
        return PointForces()

    with open_carto_file(file, mode='rb') as f:
        # read file version
        version = f.readline().decode(encoding=encoding).rstrip()
        if not version.lower().endswith('contactforce.txt_2.0'):
            log.warning('version in file {} is not supported'
                        .format(file.name))
            return PointForces()

        line = f.readline().decode(encoding=encoding).rstrip()
        token = 'Rate='
        rate = line[line.find(token) + len(token):].split()[0]
        if not rate == '50':
            log.debug('unexpected rate ({}) found in force file {}'
                      .format(rate, file))
        token = 'Number ='
        num_points = line[line.find(token) + len(token):].split()[0]
        if not num_points == '200':
            log.debug('unexpected number of points ({}) found in force file {}'
                      .format(num_points, file))

        line = f.readline().decode(encoding=encoding).rstrip()
        token = 'Mode='
        mode = line[line.find(token) + len(token):].split()[0]
        if not mode == '0':
            log.debug('unexpected mode ({}) found in force file {}'
                      .format(mode, file))

        # ignore lines 4 - 6
        _ = f.readline()
        _ = f.readline()
        _ = f.readline()

        line = f.readline().decode(encoding=encoding).rstrip()
        items = line.split()
        force_data['force'] = float(items[1])
        force_data['axialAngle'] = float(items[2])
        force_data['lateralAngle'] = float(items[3])

        line = f.readline().decode(encoding=encoding).rstrip()
        header_lines = 8
        if not line.lower().startswith('index'):
            header_lines = 9
            log.debug('unexpected header line (8) in {}, trying next line'
                      .format(file.name))
            line = f.readline().decode(encoding=encoding).rstrip()
            if not line.lower().startswith('index'):
                log.warning('unexpected file header in {}'.format(file.name))
                return PointForces()

        if isinstance(file, zipfile.Path):
            data = np.loadtxt(file.open(),
                              dtype=np.float32,
                              skiprows=header_lines,
                              usecols=[1, 3, 4, 5, 2])
        else:
            data = np.loadtxt(file,
                              dtype=np.float32,
                              skiprows=header_lines,
                              usecols=[1, 3, 4, 5, 2])

        force_data['t_time'] = data[:, 0]
        force_data['t_force'] = data[:, 1]
        force_data['t_axialAngle'] = data[:, 2]
        force_data['t_lateralAngle'] = data[:, 3]
        force_data['systemTime'] = data[:, 4]

        return PointForces(force=force_data['force'],
                           axial_angle=force_data['axialAngle'],
                           lateral_angle=force_data['lateralAngle'],
                           t_time=force_data['t_time'],
                           t_force=force_data['t_force'],
                           t_axial_angle=force_data['t_axialAngle'],
                           t_lateral_angle=force_data['t_lateralAngle'],
                           system_time=force_data['systemTime']
                           )


def read_visitag_file(file, encoding='cp1252'):
    """
    Reads a Carto3 VisiTag file.

    Any type of VisiTag file can be read. File header is always one line
    followed by data.

    Parameters:
        file : string
            path to VisiTag file
        encoding :

    Raises:
        ValueError : If number of column headers does not match data shape

    Returns:
        ndarray (n_cols, n_data) : file data
        list of string : column header names
    """

    # create child logger
    log = logging.getLogger('{}.read_visitag_file'.format(__name__))
    log.debug('reading visitag file {}'.format(file))

    # define data order
    ORDER = ['SiteIndex',
             'Session',
             'ChannelID',
             'TagIndexStatus',
             'X',
             'Y',
             'Z',
             'DurationTime',
             'AverageForce',
             'MaxTemperature',
             'MaxPower',
             'BaseImpedance',
             'ImpedanceDrop',
             'FTI',
             'RFIndex']

    if not carto_isfile(file):
        log.info('VisiTags file {} not found'.format(file))
        return np.array([], dtype=float, ndmin=2), list()

    # read header information
    with open_carto_file(file, mode='rb') as f:
        col_headers = f.readline().decode(encoding=encoding).rstrip().split()
        if not f.readline().decode(encoding=encoding):
            # file is empty!
            return np.array([], dtype=float, ndmin=2), []

    # locate significant data
    try:
        cols = get_col_idx_from_header(col_headers, ORDER)
        col_headers = [col_headers[i] for i in cols]
    except ValueError as err:
        log.warning('Unable to load Visitag data: {}'.format(err))
        return np.array([], dtype=float, ndmin=2), []

    # sanity check, just in case
    if col_headers != ORDER:
        log.warning('requested column order does not match retrieved order!')
        return np.array([], dtype=float, ndmin=2), []

    # read data
    if isinstance(file, zipfile.Path):
        data = np.loadtxt(file.open(),
                          dtype=float,
                          skiprows=1,
                          ndmin=2,
                          usecols=cols)
    else:
        data = np.loadtxt(file,
                          dtype=float,
                          skiprows=1,
                          ndmin=2,
                          usecols=cols)

    return data, ORDER
