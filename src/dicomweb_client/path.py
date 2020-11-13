"""Utilities for DICOMweb path manipulation."""
import attr
import enum
import re
from typing import Optional
import urllib.parse as urlparse


class Type(enum.Enum):
    """Type of DICOM resource the path points to."""
    SERVICE = 'service'
    STUDY = 'study'
    SERIES = 'series'
    INSTANCE = 'instance'


# For DICOM Standard spec validation of path UID components.
_MAX_UID_LENGTH = 64
_REGEX_UID = re.compile(r'[0-9]+([.][0-9]+)*')


class Path:
    """Represents a fully qualified HTTPS URL to a DICOMweb resource.

    http://dicom.nema.org/dicom/2013/output/chtml/part18/sect_6.7.html

    Given an HTTPS *service_url*, a valid DICOMweb-compatible URL would be:
    - '<service_url>' (no DICOMWeb suffix)
    - '<service_url>/studies/<study_uid>'
    - '<service_url>/studies/<study_uid>/series/<series_uid>'
    - '<service_url>/studies/<study_uid>/series/<series_uid>/instances/ \
        <instance_uid>'
    """

    def __init__(
            self,
            service_url: str,
            study_uid: Optional[str] = None,
            series_uid: Optional[str] = None,
            instance_uid: Optional[str] = None):
        """Instantiates an object.

        As per the DICOM Standard, the Study, Series, and Instance UIDs must be
        a series of numeric components ("0"-"9") separated by the period "."
        character, with a maximum length of 64 characters.

        Parameters
        ----------
        service_url: str
            DICOMweb service HTTPS URL. Trailing forward slashes are not
            permitted.
        study_uid: Optional[str]
            DICOM Study UID.
        series_uid: Optional[str]
            DICOM Series UID.
        instance_uid: Optional[str]
            DICOM SOP Instance UID.

        Raises
        ------
        ValueError:
            In the following cases:
            - *service_url* has a trailing slash.
            - *service_url* does not use the HTTPS addressing scheme.
            - *service_url* is incompatible with the DICOMweb standard.
            - *series_uid* is supplied without *study_uid*.
            - *instance_uid* is supplied without *study_uid* or *series_uid*.
            - Any one of *study_uid*, *series_uid*, or *instance_uid* does not
              meet the DICOM Standard UID spec in the docstring.
        """
        _validate_service_url(service_url)
        _validate_uids(study_uid, series_uid, instance_uid)
        self._service_url = service_url
        self._study_uid = study_uid
        self._series_uid = series_uid
        self._instance_uid = instance_uid

    def __str__(self) -> str:
        """Returns the path as a DICOMweb URL string."""
        parts = (('studies', self.study_uid), ('series', self.series_uid),
                 ('instances', self.instance_uid))
        dicomweb_suffix = '/'.join(
            f'{part}/{part_uid}' for part, part_uid in parts
            if part_uid is not None)
        # Remove the trailing slash in case the suffix is empty.
        return f'{self.service_url}/{dicomweb_suffix}'.rstrip('/')

    @property
    def service_url(self) -> str:
        """Returns the Service URL."""
        return self._service_url

    @property
    def study_uid(self) -> Optional[str]:
        """Returns the Study UID, if available."""
        return self._study_uid

    @property
    def series_uid(self) -> Optional[str]:
        """Returns the Series UID, if available."""
        return self._series_uid

    @property
    def instance_uid(self) -> Optional[str]:
        """Returns the Instance UID, if available."""
        return self._instance_uid

    @property
    def type(self) -> Type:
        """The *Type* of DICOM resource referenced by the path."""
        if self.study_uid is None:
            return Type.SERVICE
        elif self.series_uid is None:
            return Type.STUDY
        elif self.instance_uid is None:
            return Type.SERIES
        return Type.INSTANCE

    def get_service_path(self) -> 'Path':
        """Returns the sub-path for the DICOMweb service within this path."""
        return Path(self.service_url)

    def get_study_path(self) -> 'Path':
        """Returns the sub-path for the DICOM Study within this path."""
        if self.type == Type.SERVICE:
            raise ValueError('Cannot get a Study path from a Service path.')
        return Path(self.service_url, self.study_uid)

    def get_series_path(self) -> 'Path':
        """Returns the sub-path for the DICOM Series within this path."""
        if self.type in (Type.SERVICE, Type.STUDY):
            raise ValueError(
                f'Cannot get a Series path from a {self.type!r} path.')
        return Path(self.service_url, self.study_uid, self.series_uid)

    @classmethod
    def from_string(cls,
                    dicomweb_url: str,
                    path_type: Optional[Type] = None) -> 'Path':
        """Parses the string to return the Path.

        Any valid DICOMweb compatible HTTPS URL is permitted, e.g.,
        '<SERVICE>/studies/<StudyInstanceUID>/series/<SeriesInstanceUID>'

        Parameters
        ----------
        dicomweb_url: str
            An HTTPS DICOMweb-compatible URL.
        path_type: Optional[Type]
            The expected DICOM resource type referenced by the path. If set, it
            validates that the resource-scope of the *dicomweb_url* matches the
            expected type.

        Returns
        -------
        The newly constructed *Path* object.

        Raises
        ------
        ValueError:
            If the path cannot be parsed or the actual path type doesn't match
            the specified expected *path_type*.
        """
        study_uid, series_uid, instance_uid = None, None, None
        # The URL format validation will happen when *Path* is returned at the
        # end.
        service_url_and_suffix = dicomweb_url.rsplit('/studies/', maxsplit=1)
        service_url = service_url_and_suffix[0]

        if len(service_url_and_suffix) > 1:
            dicomweb_suffix = f'studies/{service_url_and_suffix[1]}'
            parts = dicomweb_suffix.split('/')
            while parts:
                part = parts.pop(0)
                if part == 'studies' and parts:
                    study_uid = parts.pop(0)
                elif part == 'series' and study_uid is not None and parts:
                    series_uid = parts.pop(0)
                elif part == 'instances' and series_uid is not None and parts:
                    instance_uid = parts.pop(0)
                else:
                    raise ValueError(
                        f'Error parsing the suffix {dicomweb_suffix!r} from '
                        f'URL: {dicomweb_url!r}')

        path = cls(service_url, study_uid, series_uid, instance_uid)
        # Validate that the path is of the specified type, if applicable.
        if path_type is not None and path.type != path_type:
            raise ValueError(
                f'Unexpected path type. Expected: {path_type!r}, Actual: '
                f'{path.type!r}. Path: {dicomweb_url!r}')

        return path


def _validate_service_url(url: str) -> None:
    """Validates the Service URL supplied to `Path`."""
    parse_result = urlparse.urlparse(url)
    if parse_result.scheme != 'https':
        raise ValueError(f'Not an HTTPS URL: {url!r}')
    if url.endswith('/'):
        raise ValueError(
            f'Service URL cannot have a trailing forward slash: {url!r}')


def _validate_uids(
        study_uid: Optional[str],
        series_uid: Optional[str],
        instance_uid: Optional[str]) -> None:
    """Validates UID parameters for the `Path` constructor."""
    if study_uid is None and not (series_uid is None and instance_uid is None):
        raise ValueError(
            'study_uid missing with non-empty series_uid or instance_uid. '
            f'series_uid: {series_uid!r}, instance_uid: {instance_uid!r}')

    if series_uid is None and instance_uid is not None:
        raise ValueError('series_uid missing with non-empty instance_uid. '
                         f'instance_uid: {instance_uid!r}')

    for uid in (study_uid, series_uid, instance_uid):
        if uid is not None:
            _validate_uid(uid)


def _validate_uid(uid: str):
    """Validates a DICOM UID."""
    if len(uid) > _MAX_UID_LENGTH:
        raise ValueError('UID cannot have more than 64 chars. '
                         f'Actual count in {uid!r}: {len(uid)}')
    if not _REGEX_UID.fullmatch(uid):
        raise ValueError(f'UID {uid!r} must match regex {_REGEX_UID!r}.')
