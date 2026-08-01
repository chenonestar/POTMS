using Dapper;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages;

/// <summary>全局搜索：跨备案 / 证照 / 明细 / 撤控 / 领用，按姓名、身份证、证件号匹配。</summary>
public class SearchModel(Db db, Flash flash) : AppPageModel(flash)
{
    public string Q { get; private set; } = "";
    public List<PersonnelFiling> Filings { get; private set; } = [];
    public List<POTMS.Data.Certificate> Certificates { get; private set; } = [];
    public List<TravelDetail> Travels { get; private set; } = [];
    public List<DecontrolFiling> Decontrols { get; private set; } = [];
    public List<CertIssuance> Issuances { get; private set; } = [];
    public int Total => Filings.Count + Certificates.Count + Travels.Count + Decontrols.Count + Issuances.Count;

    public void OnGet(string? q)
    {
        Q = (q ?? "").Trim();
        if (Q.Length == 0) return;
        var like = $"%{Q}%";
        using var cn = db.Open();

        Filings = cn.Query<PersonnelFiling>(
            "SELECT * FROM personnel_filing WHERE surname || given_name LIKE @l OR id_number LIKE @l " +
            "OR work_unit LIKE @l ORDER BY created_at DESC LIMIT 50", new { l = like }).AsList();
        Certificates = cn.Query<POTMS.Data.Certificate>(
            "SELECT * FROM certificates WHERE name LIKE @l OR passport_no LIKE @l OR hm_pass_no LIKE @l " +
            "OR tw_pass_no LIKE @l ORDER BY updated_at DESC LIMIT 50", new { l = like }).AsList();
        Travels = cn.Query<TravelDetail>(
            "SELECT * FROM travel_details WHERE name LIKE @l OR id_number LIKE @l OR passport_no LIKE @l " +
            "OR destination_passport LIKE @l ORDER BY created_at DESC LIMIT 50", new { l = like }).AsList();
        Decontrols = cn.Query<DecontrolFiling>(
            "SELECT * FROM decontrol_filing WHERE surname || given_name LIKE @l OR id_number LIKE @l " +
            "ORDER BY created_at DESC LIMIT 50", new { l = like }).AsList();
        Issuances = cn.Query<CertIssuance>(
            "SELECT i.*, pf.work_unit AS work_unit FROM cert_issuance i " +
            "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id " +
            "WHERE i.holder_name LIKE @l OR i.id_number LIKE @l OR i.cert_nos LIKE @l " +
            "ORDER BY i.issue_date DESC LIMIT 50", new { l = like }).AsList();
    }
}
