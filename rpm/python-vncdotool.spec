# A basic RPM packaging for VNCDoTool with both Python 2 and 3.

Name:           python-vncdotool
Version:        0.12.0
Release:        0%{?dist}
Summary:        A command line VNC client and python library
Group:          Development/Languages
License:        MIT
URL:            https://pypi.org/project/vncdotool/
Source0:        https://files.pythonhosted.org/packages/2f/99/c5dfe95a64b203c113735d4bc86428b87ebb1dfc45b7322bdbbaf2b6b06d/vncdotool-%{version}.tar.gz

BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildArch:      noarch 

BuildRequires:  gcc
BuildRequires:  redhat-rpm-config
BuildRequires:  python-devel
BuildRequires:  python-setuptools
Requires:       python-twisted


%description
A command line VNC client and python library

%package -n python3-vncdotool
Summary:        A command line VNC client and python library
Group:          Development/Languages
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       python3-twisted
%description -n python3-vncdotool
A command line VNC client and python library

%prep
%setup -q -n vncdotool-%{version}
rm -rf %{py3dir}
cp -a . %{py3dir}

%build
%{__python} setup.py build

pushd %{py3dir}
%{__python3} setup.py build
popd

%install
%{__python} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT

pushd %{py3dir}
%{__python3} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT
popd

%files
%defattr(-,root,root,-)
#%doc README.txt
%{python_sitelib}/vncdotool/*.py*
%{python_sitelib}/vncdotool-*.egg-info
/usr/bin/vncdo
/usr/bin/vncdotool
/usr/bin/vnclog

%files -n python3-vncdotool
%defattr(-,root,root,-)
%{python3_sitelib}/vncdotool/*.py*
%{python3_sitelib}/vncdotool/__pycache__/*.cpython-3?.py*
%{python3_sitelib}/vncdotool/__pycache__/*.cpython-3?.opt-1.py*
%{python3_sitelib}/vncdotool-*.egg-info
